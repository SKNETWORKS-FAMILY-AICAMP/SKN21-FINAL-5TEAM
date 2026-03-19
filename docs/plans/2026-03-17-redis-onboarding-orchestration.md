# Redis Onboarding Orchestration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redis 기반 lightweight queue, run/job/event 상태 모델, FastAPI SSE 스트림을 도입해 onboarding orchestrator를 병렬 실행과 실시간 관찰이 가능한 구조로 전환한다.

**Architecture:** 기존 직렬 orchestrator를 한 번에 제거하지 않고, 먼저 Redis state/event adapter와 SSE endpoint를 추가한 뒤 synthetic job event를 발행하게 만든다. 이후 worker queue, scheduler reducer, approval blocked-job 모델, retry/reaper를 단계적으로 붙여 Analyzer/Planner/Generator/Validator 흐름을 queue 기반으로 이전한다.

**Tech Stack:** Python, FastAPI, Redis, pytest, onboarding orchestrator, SSE, worker process

---

### Task 1: Introduce Redis-backed run/job/event contracts

**Files:**
- Create: `chatbot/src/onboarding/redis_models.py`
- Create: `chatbot/src/onboarding/redis_store.py`
- Test: `chatbot/tests/onboarding/test_redis_store.py`

**Step 1: Write the failing test**

`test_redis_store.py`에 다음 검증을 추가한다.
- run 생성 시 `onboarding:run:{run_id}` hash가 기록된다
- job 생성 시 `onboarding:job:{job_id}` hash와 run job set이 기록된다
- event append 시 `onboarding:events:{run_id}`에 저장된다

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_redis_store.py -v`
Expected: FAIL because Redis store module does not exist yet

**Step 3: Write minimal implementation**

`redis_models.py`, `redis_store.py`에:
- `RunRecord`
- `JobRecord`
- `RunEventRecord`
- run/job/event CRUD helper
- Redis key builder

를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_redis_store.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/redis_models.py chatbot/src/onboarding/redis_store.py chatbot/tests/onboarding/test_redis_store.py
git commit -m "feat: add redis onboarding state store"
```

### Task 2: Add scheduler reducer and ready-queue primitives

**Files:**
- Create: `chatbot/src/onboarding/job_scheduler.py`
- Test: `chatbot/tests/onboarding/test_job_scheduler.py`

**Step 1: Write the failing test**

`test_job_scheduler.py`에:
- dependency 없는 job이 runnable로 분류되는지
- upstream 완료 이벤트 후 dependent job이 unblock되는지
- failed event 후 diagnoser job 제안이 생성되는지

를 검증하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_job_scheduler.py -v`
Expected: FAIL because scheduler reducer does not exist yet

**Step 3: Write minimal implementation**

`job_scheduler.py`에:
- runnable 판정 함수
- event reducer
- next job proposal 계산
- retryable vs structural failure routing

를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_job_scheduler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/job_scheduler.py chatbot/tests/onboarding/test_job_scheduler.py
git commit -m "feat: add onboarding job scheduler reducer"
```

### Task 3: Add event publisher and synthetic job events to current orchestrator

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/agent_contracts.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing test**

`test_orchestrator.py`에 기존 직렬 run이 실행되더라도:
- run created event가 발행되고
- Analyzer/Planner/Generator/Validator 구간에서 synthetic `job.started` / `job.completed` 이벤트가 남고
- 결과 payload에 run event stream 식별자가 포함되는지

를 검증하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k redis_events -v`
Expected: FAIL because orchestrator does not emit run/job events yet

**Step 3: Write minimal implementation**

`orchestrator.py`, `agent_contracts.py`에서:
- run/job/event 공통 payload 연결
- 기존 단계 시작/완료를 synthetic job event로 발행
- Redis store 주입점 추가

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k redis_events -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/agent_contracts.py chatbot/tests/onboarding/test_orchestrator.py
git commit -m "feat: emit onboarding run and job events"
```

### Task 4: Add onboarding SSE stream endpoint

**Files:**
- Create: `chatbot/src/api/v1/endpoints/onboarding_runs.py`
- Modify: `chatbot/src/api/v1/router.py`
- Test: `chatbot/tests/api/test_onboarding_run_stream.py`

**Step 1: Write the failing test**

API 테스트에:
- run event가 있을 때 SSE endpoint가 event payload를 stream하는지
- keep-alive 또는 done event를 적절히 보내는지

를 검증하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/api/test_onboarding_run_stream.py -v`
Expected: FAIL because onboarding SSE endpoint does not exist yet

**Step 3: Write minimal implementation**

`onboarding_runs.py`에:
- `/api/v1/onboarding/runs/{run_id}/events`
- Redis event reader
- `_to_sse()` 스타일 serializer
- stream lifecycle handling

를 추가하고 router에 등록한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/api/test_onboarding_run_stream.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/api/v1/endpoints/onboarding_runs.py chatbot/src/api/v1/router.py chatbot/tests/api/test_onboarding_run_stream.py
git commit -m "feat: add onboarding run event stream endpoint"
```

### Task 5: Add worker leasing, heartbeat, and failure recovery primitives

**Files:**
- Create: `chatbot/src/onboarding/worker_runtime.py`
- Test: `chatbot/tests/onboarding/test_worker_runtime.py`

**Step 1: Write the failing test**

`test_worker_runtime.py`에:
- worker가 job lease를 획득하면 owner/lease timestamps가 기록되는지
- heartbeat 갱신이 TTL과 job hash를 갱신하는지
- 만료된 lease가 stalled 상태로 판정되는지

를 검증하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_worker_runtime.py -v`
Expected: FAIL because worker runtime primitives do not exist yet

**Step 3: Write minimal implementation**

`worker_runtime.py`에:
- `lease_job`
- `heartbeat_job`
- `complete_job`
- `fail_job`
- stalled detection helper

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_worker_runtime.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/worker_runtime.py chatbot/tests/onboarding/test_worker_runtime.py
git commit -m "feat: add onboarding worker lease runtime"
```

### Task 6: Add queue worker process for role jobs

**Files:**
- Create: `chatbot/src/onboarding/worker_process.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Test: `chatbot/tests/onboarding/test_worker_process.py`

**Step 1: Write the failing test**

`test_worker_process.py`에:
- ready queue에 있는 Analyzer/Planner job을 worker가 가져가 실행하는지
- 실행 결과가 job result와 `job.completed` 이벤트에 반영되는지

를 검증하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_worker_process.py -v`
Expected: FAIL because worker process loop does not exist yet

**Step 3: Write minimal implementation**

`worker_process.py`, `role_runner.py`에서:
- 범용 worker loop
- job kind -> executor dispatch
- role runner를 job payload 기반으로 호출하는 adapter

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_worker_process.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/worker_process.py chatbot/src/onboarding/role_runner.py chatbot/tests/onboarding/test_worker_process.py
git commit -m "feat: run onboarding role jobs from worker process"
```

### Task 7: Move approval gates into blocked-job model

**Files:**
- Modify: `chatbot/src/onboarding/agent_orchestrator.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/approval_store.py`
- Test: `chatbot/tests/onboarding/test_approval_gates.py`

**Step 1: Write the failing test**

approval 테스트에:
- analysis/apply/export approval이 `approval.requested` 이벤트를 발행하는지
- approve 전까지 downstream job이 blocked 상태인지
- approve 시 unblock되고 reject 시 terminal state로 가는지

를 검증하는 케이스를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_gates.py -v`
Expected: FAIL because approval is still modeled as direct state jump

**Step 3: Write minimal implementation**

관련 파일에서:
- approval job payload
- blocked 상태 관리
- approval resolution -> scheduler wake-up 연결

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_gates.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/agent_orchestrator.py chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/approval_store.py chatbot/tests/onboarding/test_approval_gates.py
git commit -m "feat: model onboarding approvals as blocked jobs"
```

### Task 8: Parallelize independent validation/evaluation work

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/backend_evaluator.py`
- Modify: `chatbot/src/onboarding/frontend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1: Write the failing test**

integration test에:
- backend/frontend evaluation이 독립 job으로 queue에 등록되고
- 두 작업이 병렬 실행되더라도 최종 validation summary가 안정적으로 만들어지는지

를 검증하는 케이스를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k parallel_validation -v`
Expected: FAIL because validation is still sequential

**Step 3: Write minimal implementation**

`orchestrator.py` 등에서:
- backend/frontend evaluation을 독립 job으로 분리
- completion join logic 추가
- validation summary reducer 보강

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_agent_integration.py -k parallel_validation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/orchestrator.py chatbot/src/onboarding/backend_evaluator.py chatbot/src/onboarding/frontend_evaluator.py chatbot/tests/onboarding/test_agent_integration.py
git commit -m "feat: parallelize onboarding validation jobs"
```

### Task 9: Add stalled-job reaper and retry orchestration

**Files:**
- Create: `chatbot/src/onboarding/reaper.py`
- Modify: `chatbot/src/onboarding/job_scheduler.py`
- Test: `chatbot/tests/onboarding/test_reaper.py`

**Step 1: Write the failing test**

`test_reaper.py`에:
- expired lease job이 retry budget 안이면 재큐잉되는지
- retry budget 초과 또는 structural failure면 failed/human review로 전환되는지

를 검증하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_reaper.py -v`
Expected: FAIL because reaper module does not exist yet

**Step 3: Write minimal implementation**

`reaper.py`, `job_scheduler.py`에:
- stalled job scan
- retry enqueue
- diagnoser proposal
- terminal escalation

를 구현한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_reaper.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/reaper.py chatbot/src/onboarding/job_scheduler.py chatbot/tests/onboarding/test_reaper.py
git commit -m "feat: recover stalled onboarding jobs"
```

### Task 10: Verify migration slice and update docs

**Files:**
- Modify: `docs/plans/2026-03-17-redis-onboarding-orchestration-design.md` if implementation notes change

**Step 1: Run targeted tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_redis_store.py -v`
- `uv run pytest chatbot/tests/onboarding/test_job_scheduler.py -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k redis_events -v`
- `uv run pytest chatbot/tests/api/test_onboarding_run_stream.py -v`
- `uv run pytest chatbot/tests/onboarding/test_worker_runtime.py -v`
- `uv run pytest chatbot/tests/onboarding/test_worker_process.py -v`
- `uv run pytest --noconftest chatbot/tests/onboarding/test_approval_gates.py -v`
- `uv run pytest chatbot/tests/onboarding/test_reaper.py -v`

Expected: PASS

**Step 2: Run broader onboarding regression slice**

Run: `uv run pytest chatbot/tests/onboarding -q`
Expected: PASS or known unrelated failures documented

**Step 3: Manual verification**

확인 항목:
- Redis에 run/job/event key가 생성되는지
- SSE endpoint에서 live timeline이 보이는지
- worker 중 하나를 중단하면 stalled recovery가 동작하는지
- approval pending 동안 downstream job이 blocked로 유지되는지

**Step 4: Commit**

```bash
git add docs/plans/2026-03-17-redis-onboarding-orchestration-design.md
git commit -m "docs: record redis onboarding orchestration rollout"
```
