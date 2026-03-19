# Onboarding Debug Logging Design

## Goal
LLM-first onboarding 파이프라인의 내부 진행 상태를 파일/단계 기준으로 추적 가능하게 만든다.

## Logging Layers

### 1. execution-trace.jsonl
- 단계별 이벤트 append
- 예: `analysis_started`, `llm_role_failed`, `patch_proposal_written`, `merge_simulation_passed`
- 필드:
  - `event`
  - `timestamp`
  - `run_id`
  - `status`
  - `related_files`
  - `details`

### 2. reports/llm-debug/*.json
- 단계별 상세 로그
- 예:
  - `llm-debug/analyzer.json`
  - `llm-debug/codebase-interpretation.json`
  - `llm-debug/patch-proposal.json`
  - `llm-debug/patch-draft.json`
- 필드:
  - `input_summary`
  - `sampled_files`
  - `raw_response`
  - `normalized_response`
  - `status`
  - `error_type`
  - `error_message`
  - `fallback_used`

### 3. file-activity.json
- 파일 기준 활동 인덱스
- 예:
  - analyzed_by
  - selected_by
  - patched_by
  - validated_by

## Scope
- codebase interpretation
- role runner
- patch proposal
- patch draft
- merge simulation

## Testing
- trace file 생성
- llm debug file 생성
- file activity 인덱스에 target file 포함
