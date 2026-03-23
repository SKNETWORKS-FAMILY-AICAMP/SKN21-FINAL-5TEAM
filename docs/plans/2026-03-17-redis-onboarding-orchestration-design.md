# Redis Onboarding Orchestration Design

## Goal
온보딩 orchestrator를 Redis 기반 경량 큐, 실시간 SSE 진행 스트림, 동적 job scheduler 구조로 전환해 subagent 작업을 병렬 실행하고 관찰 가능하게 만든다.

## Problem
현재 onboarding 파이프라인은 단일 상태 머신과 동기 role invocation 중심이라 실질적으로 `Analyzer -> Planner -> Generator -> Validator` 순차 흐름에 가깝다.

- run 전체 상태는 하나의 `RunState`에 수렴되어 있다.
- approval도 단일 `pending_approval`로만 표현된다.
- role 실행은 동기 `llm.invoke()` 기반이라 동시에 여러 subagent가 살아 있지 않다.
- Slack/trace는 role 완료 시점 중심이라 "아직 작업 중", "방금 끝남", "새 작업이 열림" 같은 실시간 진행감이 약하다.

사용자가 원하는 것은 다음 세 가지다.

1. subagent에게 작업을 병렬로 맡길 것
2. 각 subagent의 진행과 완료를 실시간으로 확인할 것
3. 고정된 순서가 아니라 현재 상황에 따라 다음 작업을 유동적으로 바꿀 것

## Recommended Approach
Redis를 단일 백플레인으로 두고 onboarding 실행 모델을 `run + jobs + events` 구조로 재설계한다.

- Redis list 또는 stream을 ready queue로 사용한다.
- Redis hash/set으로 run/job 상태를 저장한다.
- Redis stream 또는 pub/sub로 live event를 발행한다.
- FastAPI SSE endpoint는 Redis 이벤트를 읽어 프론트로 바로 전달한다.
- orchestrator는 더 이상 role을 직접 순차 호출하지 않고, 이벤트를 소비하면서 새 job을 동적으로 enqueue한다.
- worker는 role 실행 주체가 되며 `started / heartbeat / progress / completed / failed / artifact_written` 이벤트를 발행한다.

권장안은 Redis primitives를 직접 사용하는 것이다.

- RQ/Dramatiq보다 job graph와 live event contract를 세밀하게 통제하기 쉽다.
- Celery보다 현재 코드베이스와 요구사항에 비해 가볍다.
- 추후 필요 시 worker 실행기를 교체해도 Redis key/event contract는 유지할 수 있다.

## Alternatives Considered

### 1. Keep current pipeline and add better logs only
- 장점: 구현 범위가 가장 작다
- 단점: 실시간 관찰은 가능해져도 실제 병렬 실행과 동적 orchestration은 얻지 못한다

### 2. In-process asyncio scheduler
- 장점: 현재 코드와 붙이기 쉽고 개발 속도가 빠르다
- 단점: 프로세스 장애 격리, worker 확장, long-running job 회수 측면에서 한계가 있다

### 3. Redis-backed lightweight distributed scheduler
- 장점: 실제 병렬 실행, 실시간 상태 공유, worker 확장, zombie recovery를 균형 있게 제공한다
- 단점: 상태 모델과 lease/retry 규칙을 새로 정의해야 한다

### 4. Celery-style orchestration
- 장점: 재시도와 워커 운영 기능이 풍부하다
- 단점: 현재 문제 규모에 비해 무겁고, 동적 graph/event 관찰을 맞춤 구현해야 한다

권장안은 3번이다.

## Scope

### In scope
- `run/job/event` 도메인 모델 도입
- Redis 기반 ready queue, state store, event stream 설계
- worker lease, heartbeat, retry, stalled recovery 규칙 정의
- FastAPI onboarding run SSE endpoint 추가
- 현재 onboarding orchestrator를 event-driven scheduler로 전환하기 위한 중간 단계 설계
- approval을 queue-aware blocked state로 재모델링

### Out of scope
- Redis 외 별도 durable database 도입
- multi-tenant auth, RBAC, production deployment topology
- Celery/RQ 완전 통합
- 모든 기존 onboarding 세부 로직을 한 번에 병렬화하는 것

## Architecture

### Core model
기존 단일 `RunState` 중심 모델을 유지하되, 실행의 실질적 단위는 `job`으로 이동한다.

#### Run
- 하나의 onboarding 실행 전체를 나타낸다
- 공통 context, approval 상태, summary 상태를 가진다
- terminal 상태는 `completed`, `failed`, `human_review_required`, `cancelled` 정도로 요약한다

#### Job
- subagent 또는 시스템 작업 단위다
- 예시:
  - `analyzer.scan_capabilities`
  - `planner.propose_capabilities`
  - `generator.draft_overlay`
  - `validator.smoke_run`
  - `diagnostician.classify_failure`
  - `approval.apply_overlay`
- 각 job은 `role`, `status`, `depends_on`, `retry_budget`, `lease_owner`, `heartbeat_at`, `artifacts`, `result_summary`를 가진다

#### Event
- UI, Slack, logs, scheduler reactivity의 공통 원본이다
- 최소 이벤트 타입:
  - `run.created`
  - `job.queued`
  - `job.started`
  - `job.heartbeat`
  - `job.progress`
  - `artifact.written`
  - `job.completed`
  - `job.failed`
  - `approval.requested`
  - `approval.resolved`
  - `run.completed`

### Redis keys
초기 key contract는 다음처럼 단순하게 잡는다.

- `onboarding:run:{run_id}`
  - run metadata hash
- `onboarding:run:{run_id}:jobs`
  - run 소속 job id set
- `onboarding:job:{job_id}`
  - job 상태 hash
- `onboarding:queue:ready`
  - 실행 가능한 job queue
- `onboarding:events:{run_id}`
  - run 전용 event stream
- `onboarding:heartbeat:{job_id}`
  - TTL heartbeat key

필수 job hash 필드:
- `job_id`
- `run_id`
- `kind`
- `role`
- `status`
- `payload_json`
- `depends_on_json`
- `retry_count`
- `retry_budget`
- `lease_owner`
- `leased_at`
- `lease_expires_at`
- `heartbeat_at`
- `result_json`
- `error_json`

### Scheduler loop
orchestrator는 순차 함수 호출자가 아니라 event-driven coordinator가 된다.

1. run 생성
2. 초기 job seed
3. runnable job enqueue
4. worker event 소비
5. 상태 reduction
6. 새로 unblock된 job enqueue
7. terminal condition 판정

핵심 원칙:
- Planner는 "전체 순서 확정자"가 아니다
- Orchestrator가 dependency와 이벤트를 보고 실제 다음 순서를 계산한다
- 일부 결과가 먼저 오면 그 결과만으로 downstream job을 열 수 있다

### Worker model
worker는 역할별 또는 범용 executor로 실행한다.

초기 단계에서는 범용 worker 하나가 job kind를 보고 적절한 executor를 선택해도 충분하다.

job 수신 후 worker 동작:

1. queue에서 job 수신
2. lease 획득 및 `job.started` 발행
3. 주기적 heartbeat 갱신
4. 진행률/중간 산출물 이벤트 발행
5. 완료 시 `job.completed` + result 저장
6. 실패 시 `job.failed` + error 저장

### Real-time observation
실시간 관찰의 원본 채널은 FastAPI SSE다.

- 신규 endpoint 예: `/api/v1/onboarding/runs/{run_id}/events`
- SSE는 Redis stream/pubsub를 읽어 이벤트를 그대로 전달한다
- 프론트는 타임라인 뷰 또는 run board 형태로 표시한다

Slack은 보조 채널로 유지한다.

- 모든 이벤트를 Slack에 다 쏘지 않는다
- 시작, 실패, approval, 완료 같은 핵심 이벤트만 요약해 전송한다

### Approval model
approval은 더 이상 단일 전역 분기문이 아니라 특별한 blocked job으로 다룬다.

- approval 필요 시 `approval.requested` 이벤트 발행
- 관련 downstream job은 `blocked` 상태 유지
- UI 또는 Slack에서 approve/reject 결정
- orchestrator가 `approval.resolved` 이벤트를 적용하고 blocked job을 풀거나 종료한다

이 구조는 현재 `analysis/apply/export` gate와 호환되면서, 추후 finer-grained approval로 확장 가능하다.

### Retry and stalled recovery
운영 규칙은 처음부터 명시한다.

- worker는 lease와 heartbeat를 반드시 기록한다
- reaper는 `lease_expires_at`이 지난 running job을 검사한다
- retry 가능한 실패는 재큐잉한다
- 구조적 실패는 재시도하지 않고 `Diagnostician` job 또는 `human_review_required`로 전환한다
- 중복 실행 방지를 위해 모든 job은 deterministic idempotency key를 가진다

구조적 실패 예:
- patch target not found
- auth mismatch
- contract mismatch
- required artifact missing

## Data Flow

### Run creation
1. API 또는 CLI가 onboarding run 생성 요청
2. orchestrator가 run metadata를 Redis에 기록
3. `run.created` 이벤트 발행
4. 초기 job set을 seed

### Parallel execution
1. scheduler가 dependency 없는 job을 `ready` queue에 넣음
2. 여러 worker가 병렬로 job을 가져감
3. worker는 진행 중 heartbeat/progress/artifact 이벤트를 발행
4. orchestrator는 이벤트를 반영해 새 job을 열거나 blocked 상태를 유지함

### Validation and recovery
1. smoke/evaluation job이 실패
2. orchestrator가 실패 정책 분류
3. retry 가능 시 retry job 재큐잉
4. 구조적 실패면 diagnostician job enqueue
5. 필요 시 `approval.requested` 또는 `human_review_required`로 전환

### Completion
1. terminal condition 충족
2. export/summary artifacts 정리
3. `run.completed` 이벤트 발행
4. SSE 연결에는 최종 metadata 전달

## API and Event Contract

### SSE payload shape
```json
{
  "type": "job.progress",
  "run_id": "food-run-401",
  "job_id": "planner-001",
  "role": "Planner",
  "status": "running",
  "message": "capabilities 우선순위를 계산 중입니다",
  "progress": 55,
  "artifact_path": null,
  "timestamp": "2026-03-17T12:00:00+00:00"
}
```

필수 필드:
- `type`
- `run_id`
- `timestamp`

조건부 필드:
- `job_id`
- `role`
- `status`
- `message`
- `progress`
- `artifact_path`
- `details`

### Event ordering
- 같은 job 안에서는 이벤트 순서를 보장해야 한다
- run 전체에서는 near-real-time ordering이면 충분하다
- UI는 timestamp 기준 정렬 가능해야 한다

## Migration Strategy
한 번에 전체 교체하지 않는다.

### Phase 1
- Redis event publisher/store 도입
- run/job/event 모델 추가
- SSE endpoint 추가
- 기존 직렬 orchestrator에서 synthetic job event만 발행

### Phase 2
- worker process와 ready queue 도입
- Analyzer/Planner/Generator 일부를 queue 기반 job으로 분리
- approval을 blocked job 모델로 이전

### Phase 3
- validation/retry/diagnostician 흐름을 queue 기반으로 전환
- stalled recovery, reaper, idempotency 강화
- 독립 smoke/evaluation job 병렬화

이 순서면 관찰 가능성과 병렬성을 동시에 얻되, 현재 파이프라인을 전면 파괴하지 않고 전환할 수 있다.

## Testing Strategy

### Unit tests
- Redis state adapter가 run/job hash를 정확히 읽고 쓰는지 검증
- scheduler reducer가 이벤트를 받아 올바른 next job set을 계산하는지 검증
- lease/heartbeat 만료 판정이 기대대로 동작하는지 검증
- SSE serializer가 event payload를 안정적으로 변환하는지 검증

### Integration tests
- onboarding run 생성 후 초기 job들이 큐에 등록되는지 검증
- worker가 event를 발행하면 SSE endpoint에서 순서대로 관찰되는지 검증
- approval pending 시 downstream job이 blocked로 유지되는지 검증
- stalled job이 reaper에 의해 retry 또는 failure로 전환되는지 검증

### End-to-end slice
- 단일 run에서 Analyzer/Planner/Generator 두세 개 job이 병렬로 실행되는 것을 확인
- UI에서 `started -> heartbeat -> completed` 타임라인이 보이는지 확인
- 실패 시 Diagnostician job이 동적으로 추가되는지 확인

## Risks
- Redis만 source of truth로 둘 경우 장기 보존과 조회 질의는 제한적이다
- event와 state write가 원자적으로 맞물리지 않으면 UI와 scheduler 상태가 어긋날 수 있다
- worker lease/retry 구현이 부정확하면 duplicate execution이나 ghost running job이 생길 수 있다
- 기존 직렬 orchestrator와 신구 모델을 함께 운영하는 전환 구간이 가장 복잡하다

## Success Criteria
- 온보딩 run 중 여러 subagent job이 실제로 병렬 실행된다
- 프론트 SSE에서 각 job의 시작, 진행, 완료, 실패를 실시간으로 확인할 수 있다
- orchestrator가 고정 단계 분기 대신 이벤트와 dependency를 보고 다음 job을 동적으로 추가한다
- approval, retry, stalled recovery가 Redis 상태 모델에서 일관되게 처리된다
