# Redis Onboarding Orchestration Runtime Walkthrough

## Purpose
이 문서는 2026-03-17 기준으로 Redis 기반 onboarding orchestration migration이 어떤 순서로 구현되었는지, 그리고 현재 `run_onboarding_generation()` 이 실제로 어떤 방식으로 동작하는지를 설명한다.

설계 문서가 목표 구조를 설명한다면, 이 문서는 현재 코드베이스에 반영된 실제 상태를 설명한다.

핵심 질문은 두 가지다.

1. Task 1~10을 거치면서 무엇이 어떻게 바뀌었는가
2. 지금 generation run을 실행하면 내부적으로 어떤 흐름으로 움직이는가

## Summary
현재 onboarding orchestration은 완전한 event-driven DAG scheduler로 100% 전환된 상태는 아니다. 대신 다음이 구현된 하이브리드 구조다.

- Redis에 `run/job/event` 상태를 저장할 수 있다
- onboarding run 상태를 SSE로 실시간 구독할 수 있다
- worker는 queue job을 lease, heartbeat, result 저장 방식으로 실행할 수 있다
- approval은 단순 전역 분기 대신 `blocked job` 모델로 표현된다
- validation 구간의 backend/frontend evaluation은 실제로 queue worker를 통해 병렬 실행된다
- stalled lease는 reaper가 스캔해 retry 또는 human review로 복구할 수 있다

즉, 기존 직렬 orchestrator 위에 Redis 관찰면과 worker execution plane을 얹고, 일부 구간부터 실제 queue 기반 병렬 실행으로 이전한 상태다.

## What Changed By Task

### Task 1: Redis state contracts
추가 파일:

- `chatbot/src/onboarding/redis_models.py`
- `chatbot/src/onboarding/redis_store.py`
- `chatbot/tests/onboarding/test_redis_store.py`

이 단계에서 도입된 것은 Redis를 source of truth로 쓰기 위한 최소 모델이다.

- `RunRecord`
- `JobRecord`
- `RunEventRecord`
- `RedisRunJobStore`

주요 Redis key contract:

- `onboarding:run:{run_id}`
- `onboarding:run:{run_id}:jobs`
- `onboarding:job:{job_id}`
- `onboarding:events:{run_id}`
- `onboarding:queue:ready`
- `onboarding:heartbeat:{job_id}`

이 시점부터 onboarding run은 메모리 안의 상태 머신만이 아니라, Redis에 남는 run/job/event 로그를 갖게 되었다.

### Task 2: Scheduler reducer
추가 파일:

- `chatbot/src/onboarding/job_scheduler.py`
- `chatbot/tests/onboarding/test_job_scheduler.py`

이 단계에서는 아직 전체 orchestrator를 scheduler loop로 바꾸지는 않았지만, 다음 두 규칙을 코드로 고정했다.

- dependency가 없는 job은 runnable이다
- upstream job이 완료되면 dependent job이 unblock된다
- failure는 retryable/structural 여부에 따라 recovery 제안을 만든다

여기서 중요한 점은 "다음 작업은 고정 순서가 아니라 상태 변화에 따라 계산될 수 있다"는 기반을 만든 것이다.

### Task 3: Synthetic run/job events
수정 파일:

- `chatbot/src/onboarding/orchestrator.py`
- `chatbot/tests/onboarding/test_orchestrator.py`

기존 직렬 onboarding run이 유지되더라도, 이제는 Redis event stream에 다음이 남는다.

- `run.created`
- `job.started`
- `job.completed`
- `job.failed`

적용 범위:

- `Analyzer`
- `Planner`
- `Generator`
- `Validator`
- `Diagnostician`

또한 result payload에 `run_event_stream` 식별자가 들어가므로, 외부 소비자는 run이 생성된 뒤 해당 stream을 구독할 수 있다.

이 단계는 “실제 구조는 아직 직렬이지만, 관찰면은 job 단위로 바뀌는 단계”였다.

### Task 4: SSE event stream
추가/수정 파일:

- `chatbot/src/api/v1/endpoints/onboarding_runs.py`
- `chatbot/server_fastapi.py`
- `chatbot/src/core/config.py`
- `chatbot/tests/api/test_onboarding_run_stream.py`

새 endpoint:

- `GET /api/v1/onboarding/runs/{run_id}/events`

인증:

- 일반 사용자 로그인 세션이 아니라 `ONBOARDING_INTERNAL_API_TOKEN` 기반 bearer token

동작:

- Redis `onboarding:events:{run_id}` 기존 event replay
- 이후 polling으로 신규 event tail
- SSE keep-alive comment line 전송

이 단계부터 UI나 내부 dashboard는 “run이 지금 어디까지 갔는지”를 실시간으로 볼 수 있게 되었다.

### Task 5: Worker lease/heartbeat runtime
추가/수정 파일:

- `chatbot/src/onboarding/worker_runtime.py`
- `chatbot/src/onboarding/redis_store.py`
- `chatbot/tests/onboarding/test_worker_runtime.py`

이 단계는 worker가 job을 안전하게 들고 있을 수 있게 만드는 운영 규칙을 추가한 것이다.

- `lease_job()`
- `heartbeat_job()`
- `complete_job()`
- `complete_job_with_result()`
- `fail_job()`
- `is_job_stalled()`

기록되는 핵심 필드:

- `status`
- `lease_owner`
- `leased_at`
- `lease_expires_at`
- `heartbeat_at`
- `completed_at`
- `failed_at`
- `result`
- `failure_reason`

즉, worker는 이제 단순 함수 호출자가 아니라 lease 기반 실행 주체가 되었다.

### Task 6: Queue worker process
추가/수정 파일:

- `chatbot/src/onboarding/worker_process.py`
- `chatbot/src/onboarding/worker_runtime.py`
- `chatbot/src/onboarding/redis_store.py`
- `chatbot/tests/onboarding/test_worker_process.py`

이 단계에서 `WorkerProcess.consume_once()`가 도입되었다.

동작 순서:

1. ready queue에서 job pop
2. lease 획득
3. `job.started` event 발행
4. heartbeat 갱신
5. role 또는 job executor 실행
6. result 저장
7. `job.completed` 또는 `job.failed` 발행

초기 구현은 role job 중심이었다.

### Task 7: Approval blocked-job model
수정 파일:

- `chatbot/src/onboarding/agent_orchestrator.py`
- `chatbot/src/onboarding/approval_store.py`
- `chatbot/src/onboarding/orchestrator.py`
- `chatbot/tests/onboarding/test_approval_gates.py`

기존 approval은 `pending_approval` 하나만 있는 단일 게이트였다. 이 단계에서 approval은 downstream job을 막는 방식으로 표현되기 시작했다.

추가된 개념:

- `blocked_jobs`
- `blocked_job_id`
- `approval.requested` event

현재 blocked job 매핑:

- analysis approval -> `planning`
- apply approval -> `apply`
- export approval -> `export`

의미:

- approval이 요청되면 해당 downstream job은 `blocked`
- approve 되면 `unblocked`
- reject 되면 `rejected`

`pending_approval`는 하위 호환과 summary payload용으로 남아 있지만, 실제 게이트 의미는 `blocked_jobs` 쪽으로 이동했다.

### Task 8: Parallel validation jobs
수정 파일:

- `chatbot/src/onboarding/orchestrator.py`
- `chatbot/src/onboarding/worker_process.py`
- `chatbot/src/onboarding/redis_store.py`
- `chatbot/tests/onboarding/test_agent_integration.py`

이 단계가 현재 구조에서 가장 중요한 실제 병렬 실행 지점이다.

validation 단계의 두 작업:

- backend evaluation
- frontend evaluation

이 둘을 queue job으로 등록하고, worker 두 개가 동시에 소비하게 바꿨다.

job payload 예시:

- `job_type=backend_evaluation`
- `job_type=frontend_evaluation`

`WorkerProcess`도 role job만이 아니라 generic executor job을 처리할 수 있게 확장되었다.

중요한 현재 상태:

- `Analyzer -> Planner -> Generator -> Validator` 전체가 queue 기반으로 바뀐 것은 아니다
- 하지만 validation 안의 evaluator 두 개는 event store가 있을 때 실제 병렬 worker execution으로 돈다

즉, migration은 부분적으로 실체화되었고, validation slice가 첫 번째 실제 병렬 실행 구간이다.

### Task 9: Reaper and stalled recovery
추가/수정 파일:

- `chatbot/src/onboarding/reaper.py`
- `chatbot/src/onboarding/job_scheduler.py`
- `chatbot/src/onboarding/redis_store.py`
- `chatbot/tests/onboarding/test_reaper.py`

이 단계에서 lease가 만료된 job을 복구할 수 있게 되었다.

reaper 동작:

1. run 소속 job id set 조회
2. 각 job의 `lease_expires_at` 확인
3. stalled job이면 recovery decision 계산
4. retry budget이 남아 있으면 `queued`로 복구 후 ready queue 재등록
5. budget이 끝났거나 retry 불가면 `failed` + `human_review_required`

즉, worker가 중간에 죽거나 heartbeat가 끊겨도 run이 완전히 고아가 되지 않는다.

### Task 10: Verification and cleanup
이 단계에서는 migration slice와 onboarding regression을 전체로 확인했다.

검증한 것:

- Redis store
- scheduler reducer
- synthetic run/job events
- SSE endpoint
- worker runtime
- worker process
- approval blocked-job
- reaper
- parallel validation integration
- onboarding 전체 회귀

추가로 unrelated regression 1건을 고쳤다.

- `chatbot/scripts/run_generator_eval.py`
- 문제: `sys.path` 보정 전에 `chatbot...` import
- 결과: CLI 실행 시 `ModuleNotFoundError`
- 수정: import 순서를 바꿔 repo root가 먼저 path에 올라오게 함

최종 regression 결과:

- `chatbot/tests/onboarding -q`
- `253 passed`

## Current Architecture

### High-level shape
현재 구조를 단순화하면 다음과 같다.

```text
run_onboarding_generation()
  -> 직렬 orchestrator 흐름 유지
  -> Redis run/job/event 기록
  -> approval은 blocked job으로 관리
  -> validation evaluator는 queue worker로 병렬 실행
  -> SSE가 Redis event stream을 실시간 노출
  -> stalled job은 reaper가 복구 가능
```

즉, 완전한 분산 scheduler가 아니라 “직렬 orchestrator + queue-executed subflows + 실시간 event plane” 구조다.

### Main runtime components

#### 1. `run_onboarding_generation()`
파일:

- `chatbot/src/onboarding/orchestrator.py`

역할:

- run의 상위 제어 흐름
- artifact 생성
- approval 처리
- synthetic role event 발행
- validation evaluator queue 실행 연결

#### 2. `RedisRunJobStore`
파일:

- `chatbot/src/onboarding/redis_store.py`

역할:

- run/job/event CRUD
- ready queue push/pop
- run job set 조회

#### 3. `WorkerRuntime`
파일:

- `chatbot/src/onboarding/worker_runtime.py`

역할:

- lease/heartbeat/result/failure lifecycle 관리

#### 4. `WorkerProcess`
파일:

- `chatbot/src/onboarding/worker_process.py`

역할:

- queue 소비
- role job 또는 generic executor job 실행
- `job.started/completed/failed` event 발행

#### 5. `AgentOrchestrator`
파일:

- `chatbot/src/onboarding/agent_orchestrator.py`

역할:

- 상위 run state
- retry count
- `pending_approval`
- `blocked_jobs`

#### 6. SSE endpoint
파일:

- `chatbot/src/api/v1/endpoints/onboarding_runs.py`

역할:

- Redis event replay + live tail
- internal service token auth

#### 7. `reap_stalled_jobs()`
파일:

- `chatbot/src/onboarding/reaper.py`

역할:

- stalled lease 복구
- 재큐잉 또는 human review escalation

## What Happens When Generation Runs

이 섹션은 “지금 실제로 run을 하나 실행하면 어떤 순서로 움직이는가”를 설명한다.

### 1. Run bootstrap
`run_onboarding_generation()` 이 시작되면 다음이 먼저 일어난다.

1. run bundle root 생성
2. manifest / reports / patch artifact 디렉터리 준비
3. `RunRecord`를 Redis에 저장
4. `run.created` event 발행
5. codebase map 생성

이 시점에서 외부 UI는 SSE를 통해 “run이 만들어졌다”는 사실을 바로 볼 수 있다.

### 2. Analysis phase
orchestrator는 여전히 Analyzer를 직접 호출한다.

흐름:

1. analyzer context 구성
2. `_run_role_with_events("Analyzer", ...)`
3. 내부적으로 `job.started`
4. role runner 실행
5. 완료 시 `job.completed`

이 호출은 queue worker가 아니라 orchestrator 안에서 직렬로 수행되지만, 외부에는 job 이벤트로 보인다.

즉, 관찰면은 job 단위지만 실행면은 아직 직렬이다.

### 3. Analysis approval gate
analysis가 끝나면 approval이 요청된다.

현재 동작:

1. `AgentOrchestrator.request_analysis_approval()`
2. `blocked_jobs["planning"] = blocked`
3. approval store에 request 기록
4. `approval.requested` event 발행

결정 처리:

- approve -> `planning` unblock, state는 `PLANNING`
- reject -> run은 `REJECTED`

자동 실행 환경에서는 `approval_decisions`가 있으면 이 단계가 즉시 소비된다.

### 4. Planning phase
Planner도 현재는 orchestrator가 직접 호출한다.

흐름:

1. patch proposal, recommended outputs 계산
2. `_run_role_with_events("Planner", ...)`
3. `job.started`
4. planner role 실행
5. `job.completed`

### 5. Generation phase
Generator 역시 현재는 직접 호출한다.

흐름:

1. proposed files / proposed patches 계산
2. `_run_role_with_events("Generator", ...)`
3. overlay scaffold 생성
4. patch artifact materialization
5. unified diff 초안 생성

여기서도 role 실행은 직렬이지만, event stream에는 job 단위 진행이 남는다.

### 6. Apply approval gate
generation이 끝나면 apply approval이 열린다.

현재 blocked job:

- `apply`

흐름:

1. `request_apply_approval()`
2. `blocked_jobs["apply"] = blocked`
3. `approval.requested`
4. approve 시 unblock

### 7. Runtime workspace preparation
apply가 승인되면 runtime workspace를 준비한다.

이 단계에서:

- runtime copy 준비
- merge simulation
- llm patch simulation이 켜져 있으면 후보 patch simulation도 수행

merge simulation 실패 시:

- run state는 `human_review_required`
- 이후 validation 단계로 가지 않고 종료

### 8. Parallel validation evaluator jobs
merge simulation이 성공하면 현재 구조에서 가장 중요한 병렬 구간이 시작된다.

`_run_validation_evaluation_jobs()` 가 호출되며:

1. backend evaluation job 생성
2. frontend evaluation job 생성
3. 두 job을 `onboarding:queue:ready` 에 enqueue
4. worker 두 개를 띄워 `consume_once()` 병렬 실행

각 worker는:

1. job pop
2. lease 획득
3. `job.started`
4. executor 실행
5. result 저장
6. `job.completed`

이때 role runner가 아니라 `job_type` executor가 실행된다.

- `backend_evaluation` -> `evaluate_backend_workspace()`
- `frontend_evaluation` -> `evaluate_frontend_workspace()`

이 둘은 event store가 있을 때 실제 동시 시작이 가능하다.

### 9. Smoke validation and retry diagnosis
evaluation 이후에는 smoke plan이 실행된다.

현재 이 부분은 완전 queue 기반이 아니다.

흐름:

1. smoke tests 실행
2. 실패가 있으면 failure policy 분류
3. Diagnostician role 실행
4. retry 여부 판단
5. retry 가능하면 재실행
6. retry budget 초과면 human review 또는 failure 경로

즉, validation evaluator는 병렬화되었지만 smoke retry loop는 아직 orchestrator 내부 루프다.

### 10. Validator phase
smoke summary가 성공하면 Validator role을 호출한다.

흐름:

1. validator context 구성
2. `_run_role_with_events("Validator", ...)`
3. `job.started`
4. validator role 실행
5. `job.completed`

### 11. Export approval gate
validation이 끝나면 export approval이 열린다.

blocked job:

- `export`

흐름:

1. `request_export_approval()`
2. `approval.requested`
3. approve 시 unblock
4. reject 시 `REJECTED`

### 12. Export and completion
마지막으로 export source를 선택하고 patch artifact를 export한다.

완료 시:

- result payload 생성
- artifact path 정리
- `current_state`
- `pending_approval`
- `blocked_jobs`
- `run_event_stream`

이 정보가 최종 결과로 반환된다.

## Event Model In Practice

현재 관찰 가능한 대표 event는 다음과 같다.

### Run-level
- `run.created`

### Job-level
- `job.started`
- `job.completed`
- `job.failed`

현재는 heartbeat/progress/artifact.written까지 일반화되지는 않았다. lease/heartbeat 자체는 worker runtime에 있지만, live SSE event contract로 heartbeat를 지속 발행하는 구조까지는 아직 연결되지 않았다.

### Approval-level
- `approval.requested`

### What the UI can infer
이 이벤트만으로도 UI는 다음을 표현할 수 있다.

- run 생성됨
- 어떤 role/job이 시작되었는지
- 어떤 role/job이 방금 끝났는지
- 어떤 approval 때문에 막혀 있는지
- validation evaluator 두 개가 동시에 시작되었는지

## Approval Semantics In Practice

현재 approval은 세 종류다.

- `analysis`
- `apply`
- `export`

표현 방식:

- `pending_approval`: 현재 대기 중 승인 summary
- `blocked_jobs`: 실제로 막혀 있는 downstream job 상태
- `ApprovalStore`: durable request/decision 파일 저장
- `approval.requested`: live event

즉, 지금은 state machine, file-based decision store, Redis event stream이 함께 쓰이는 과도기 구조다.

## Queue And Worker Semantics In Practice

### Ready queue
- key: `onboarding:queue:ready`
- 현재는 simple list queue

### Job hash
실행 중 worker가 기록하는 대표 필드:

- `status`
- `lease_owner`
- `leased_at`
- `lease_expires_at`
- `heartbeat_at`
- `result`
- `failure_reason`
- `retry_count`
- `terminal_state`

### Worker types currently in use
현재 코드상 worker가 쓰이는 방식은 두 가지다.

1. role worker
`RoleRunner`를 통해 Analyzer/Planner 같은 role을 실행할 수 있다

2. generic executor worker
`job_type` 기반으로 backend/frontend evaluation 같은 시스템 job을 실행한다

현재 실제 production path에서 active하게 쓰이는 건 2번이 더 가깝다. role execution 전체를 worker queue로 완전히 이전하는 것은 다음 단계의 확장 지점이다.

## Stalled Recovery Semantics

`reap_stalled_jobs()` 는 run의 모든 job을 스캔한다.

판정 기준:

- `lease_expires_at < now`

복구 규칙:

- retryable이고 `retry_count < retry_budget` 이면 requeue
- 아니면 `failed` + `human_review_required`

이 구조 덕분에 worker가 죽은 경우에도:

- job이 다시 ready queue로 들어가거나
- 사람이 봐야 하는 terminal 상태로 정리된다

## What Is Fully Migrated vs Not Yet

### Already migrated
- Redis run/job/event persistence
- SSE event stream
- worker lease/heartbeat/result model
- queue worker execution
- approval blocked-job model
- validation evaluator parallel execution
- stalled reaper

### Still hybrid
- top-level orchestrator는 여전히 직렬 control function이다
- Analyzer/Planner/Generator/Validator role 전체는 아직 direct invocation 비중이 크다
- smoke retry loop는 event-driven scheduler가 아니라 내부 while loop다
- scheduler reducer는 있지만 전체 run을 driving하는 central loop로 완전히 연결되지는 않았다

이 점을 정확히 이해해야 한다.

현재 구현은 “완전한 queue-native orchestration”이 아니라 “관찰 가능하고 일부 병렬인 하이브리드 orchestration”이다.

## Why This Structure Still Matters

완전한 재작성 없이도 다음 효과를 이미 얻었다.

- 실행 상태가 Redis에 남는다
- 외부 시스템이 SSE로 live observation 할 수 있다
- worker failure를 복구할 수 있다
- approval을 downstream blocked state로 다룰 수 있다
- 적어도 validation slice에서는 실제 병렬 실행이 된다

즉, 이후 단계에서 role execution 전체를 queue-native로 옮길 때 재사용할 기반이 이미 준비된 상태다.

## Suggested Next Evolution
현재 구조에서 다음 확장 방향은 자연스럽다.

1. Analyzer/Planner/Generator/Validator 자체를 ready queue job으로 이전
2. orchestrator를 “직접 role 호출자”에서 “job scheduler + event reducer”로 축소
3. heartbeat/progress를 SSE live contract로 확장
4. approval resolution을 scheduler wake-up과 직접 연결
5. smoke retry loop도 별도 validation job graph로 분리

이 단계가 끝나면 설계 문서에서 말한 event-driven orchestration에 훨씬 가까워진다.

## Verification Snapshot
Task 10 종료 시점 기준 검증 결과:

- migration slice targeted tests: pass
- onboarding broader regression: `253 passed`

따라서 이 문서의 설명은 “의도한 설계”가 아니라 “현재 테스트로 검증된 구현 상태”를 기준으로 한다.
