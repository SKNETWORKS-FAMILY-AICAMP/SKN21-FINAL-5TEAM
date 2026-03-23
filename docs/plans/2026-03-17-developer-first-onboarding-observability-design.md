# Developer-First Onboarding Observability Design

## Goal
온보딩 파이프라인의 내부 상태를 개발자가 빠르게 디버깅할 수 있도록 canonical event model 기반의 observability 구조를 만든다. Slack/터미널 노출은 2차 목표이며, 1차 목표는 디버그 artifact와 상태 전이를 일관된 이벤트로 남기는 것이다.

## Problem
현재 로그는 `generation.log`, `execution-trace.jsonl`, `recovery-events.json`, `llm-usage.json`, `llm-debug/*.json`, Slack/터미널 출력으로 분산되어 있다. 각각 부분적으로 유용하지만, 다음 질문에 한 번에 답하기 어렵다.

- 지금 어떤 stage에 있는가
- 어떤 component가 결정을 내렸는가
- `llm`, `recovered_llm`, `hard_fallback` 중 무엇이 채택됐는가
- recovery/fallback이 왜 발생했는가
- 다음 액션은 무엇인가

지금 구조는 log sink는 여러 개 있지만 canonical event source가 없다. 그래서 메시지 포맷이 중복되고, Slack/터미널 렌더링도 재사용하기 어렵다.

## Recommended Approach
기존 `generation.log`를 유지하되, 내부적으로는 하나의 canonical onboarding event를 먼저 정의하고 모든 sink가 그 이벤트를 렌더링하게 만든다.

- canonical event가 source of truth
- `generation.log`는 사람이 읽는 primary timeline
- `execution-trace.jsonl`은 기계용 상세 trace
- `recovery-events.json`과 `llm-usage.json`은 specialized artifact
- Slack/터미널은 canonical event의 secondary renderer

즉, "로그 파일을 더 추가"하는 것이 아니라 "모든 로그를 같은 이벤트 모델에서 파생"시키는 방향이다.

## Canonical Event Model

### Required fields
- `timestamp`
- `run_id`
- `component`
- `stage`
- `event`
- `severity`
- `summary`

### Optional fields
- `source`
- `details`
- `related_files`
- `recovery`
- `llm_usage`
- `next_action`
- `debug_artifact_path`

### Example
```json
{
  "timestamp": "2026-03-17T12:00:00+00:00",
  "run_id": "food-run-001",
  "component": "codebase_mapper",
  "stage": "analysis",
  "event": "llm_output_accepted",
  "severity": "info",
  "summary": "frontend interpretation accepted",
  "source": "recovered_llm",
  "details": {
    "provider": "openai",
    "model": "gpt-5-mini"
  },
  "recovery": {
    "applied": true,
    "reason": "framework_assessment_string_to_dict"
  },
  "debug_artifact_path": "reports/llm-debug/codebase-interpretation.json"
}
```

## Event Taxonomy

### Stage lifecycle
- `stage_started`
- `stage_completed`
- `stage_failed`

### LLM decisions
- `llm_call_started`
- `llm_output_accepted`
- `llm_output_rejected`

### Recovery path
- `recovery_started`
- `recovery_applied`
- `hard_fallback_used`

### Artifact path
- `artifact_written`
- `patch_written`
- `report_written`

### Export/runtime path
- `simulation_started`
- `simulation_completed`
- `smoke_started`
- `smoke_completed`
- `export_started`
- `export_completed`

## Ownership Model

### Logging Core
소유 파일:
- `chatbot/src/onboarding/debug_logging.py`
- `chatbot/tests/onboarding/test_debug_logging.py`

책임:
- canonical event writer
- human-readable line renderer
- JSONL event renderer

### Event Producers
소유 파일:
- `chatbot/src/onboarding/codebase_mapper.py`
- `chatbot/src/onboarding/patch_planner.py`
- `chatbot/src/onboarding/role_runner.py`
- `chatbot/src/onboarding/runtime_runner.py`
- `chatbot/src/onboarding/frontend_evaluator.py`

책임:
- local component event emission
- component-specific details/recovery metadata 첨부

### Orchestrator Integration
소유 파일:
- `chatbot/src/onboarding/orchestrator.py`

책임:
- stage transition event emission
- final run result에 canonical log artifact path 노출

### Secondary Renderers
소유 파일:
- `chatbot/src/onboarding/slack_bridge.py`

책임:
- canonical event를 Slack/terminal 친화적 텍스트로 변환
- 1차 마일스톤에서는 optional

## Why This Split
- `debug_logging.py`를 먼저 고립시키면 포맷/스키마 논의를 한 곳에 모을 수 있다.
- `orchestrator.py`는 상태 전이 owner이므로 producer이지만 formatter가 되면 안 된다.
- Slack/terminal 렌더링은 developer-first observability가 안정화된 뒤에 붙이는 게 안전하다.

## Developer-First UX Rules
- summary는 한 줄로 "무슨 일이 일어났는지" 바로 보여야 한다.
- source가 있을 때는 항상 노출한다.
- recovery/hard fallback은 reason과 영향 범위를 항상 남긴다.
- debug artifact가 있으면 경로를 항상 남긴다.
- details는 요약을 보조해야지 대체하면 안 된다.

## What Changes First

### Phase 1
- canonical event helper 추가
- existing generation log/execution trace writer를 canonical event 기반으로 정렬
- 주요 component에 taxonomy 맞는 event 추가

### Phase 2
- run summary와 Slack/terminal rendering을 canonical event 기반으로 재구성

## Non-Goals
- 모든 함수 호출 단위 trace
- 로그 저장 백엔드 도입
- 실시간 대시보드
- 운영자/비개발자용 UX를 1차 목표로 삼는 것

## Success Criteria
- 개발자가 `generation.log`와 canonical event artifact만 보고 상태 전이를 복원할 수 있다.
- recovery/hard fallback reason이 component별로 명확하게 남는다.
- Slack/terminal은 나중에 같은 event를 재사용해 렌더링할 수 있다.
- log formatting logic과 orchestration logic이 분리된다.
