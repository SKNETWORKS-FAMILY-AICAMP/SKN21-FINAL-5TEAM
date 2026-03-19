# LLM-First Codebase Interpretation Design

## Goal
deterministic `codebase-map.json` 위에 LLM이 구조 요약과 candidate ranking을 생성하고, 이후 patch planning이 이 해석을 우선 사용하도록 만든다.

## Recommended Approach
- deterministic mapper는 그대로 유지한다.
- 새 artifact `reports/llm-codebase-interpretation.json`을 만든다.
- 입력:
  - `codebase-map.json`
  - analysis
  - 후보 파일 샘플
- 출력:
  - `structure_summary`
  - `ranked_candidates`
  - `framework_assessment`
  - `source` / `fallback_reason`
- `patch proposal`은 LLM interpretation의 ranked candidate를 우선 사용한다.

## Alternatives

### Option A: interpretation artifact 추가
- 가장 작은 슬라이스
- 추천

### Option B: codebase_map 자체를 LLM으로 재작성
- 공격적이지만 failure surface가 큼

### Option C: interpretation 없이 patch proposal prompt만 확장
- 변경량은 적지만 구조 파악 artifact가 남지 않음

## Validation
- ranked candidate는 existing candidate_edit_targets 안에서만 선택
- 최대 후보 수 제한
- 비어 있으면 fallback

## Testing
- LLM interpretation 성공 시 artifact 생성
- invalid JSON / invalid candidate fallback
- patch proposal이 ranked candidate를 우선 사용
