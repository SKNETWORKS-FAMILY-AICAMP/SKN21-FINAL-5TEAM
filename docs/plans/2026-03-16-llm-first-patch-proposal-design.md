# LLM-First Patch Proposal Design

## Goal
`patch-proposal.json` 생성의 주체를 deterministic selection에서 LLM-first selection으로 옮기고, 실패 시에만 기존 규칙 기반 proposal을 fallback으로 사용한다.

## Scope
- 유지:
  - `codebase-map.json` 생성
  - deterministic patch generation / simulation / evaluation
- 변경:
  - `target_files`, `supporting_generated_files`, `recommended_outputs`, `analysis_summary`를 LLM이 먼저 제안
  - schema 위반, 빈 응답, 예외 시 deterministic proposal fallback
  - provenance artifact 기록

## Approach Options

### Option A: Patch proposal만 LLM-first
- `codebase_map + analysis + recommended_outputs`를 LLM에 제공
- `patch-proposal.json`만 LLM-first로 교체
- 추천: 가장 작은 슬라이스로 효과를 확인할 수 있음

### Option B: Analysis + patch proposal 동시 LLM-first
- Analyzer 결과와 patch proposal을 한 번에 생성
- 장점: 더 공격적
- 단점: failure surface가 커짐

### Option C: Full planner replacement
- codebase scan 이후 planning/selection/intent를 모두 LLM 전담
- 장점: 최종 목표에 가까움
- 단점: 현재 단계에는 리스크 큼

## Chosen Design
Option A.

## Data Flow
1. deterministic `codebase-map.json` 생성
2. `analysis`, `codebase_map`, `recommended_outputs`를 LLM proposal runner에 전달
3. LLM 응답을 schema 검증
4. 성공 시 `patch-proposal.json` 저장
5. 실패 시 deterministic `build_patch_proposal()` 결과 저장
6. `reports/llm-patch-proposal-execution.json`에 source/fallback_reason 기록

## Validation
- target 파일 경로가 실제 candidate set 안에 있는지 검증
- target 수 상한 유지
- 빈 `target_files` 금지

## Testing
- LLM proposal 성공 시 결과 채택
- invalid JSON / invalid payload 시 fallback
- orchestrator 통합 시 artifact 경로 생성
- Slack summary에서 fallback 여부를 표시할 수 있게 artifact 유지
