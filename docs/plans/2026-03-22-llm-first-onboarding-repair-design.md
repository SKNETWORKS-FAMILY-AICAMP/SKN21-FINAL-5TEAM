# LLM-First Onboarding Repair Design

## Goal
onboarding 파이프라인의 기본 의사결정 권한을 규칙 기반 코드에서 LLM으로 옮기고, deterministic 로직은 seam safety와 실행 가능성만 보장하는 마지막 guardrail로 축소한다.

## Problem
현재 파이프라인은 최근 개선으로 failure signature, repair history, promotion judge, seam-only repair 같은 운영 안전장치를 갖췄다. 하지만 실제 의사결정의 기본값은 여전히 deterministic 쪽에 있다.

이 구조는 최근 run들에서 반복적으로 한계를 드러냈다.

- `food-run-047`에서 build artifact가 integration contract에 남아 있어 `frontend/src/App.js` 같은 정상 source target이 LLM proposal 단계에서 탈락했다.
- deterministic frontend mount patch는 React Router 문맥을 이해하지 못해 `<Routes>` 안에 `<order-cs-widget />`를 직접 삽입했다.
- malformed patch / shape drift는 recovery가 일부 가능해졌지만, 여전히 "무엇을 바꿔야 하는가"는 규칙 엔진이 더 강하게 결정한다.

즉 지금 필요한 것은 "LLM을 보조로 쓰는 생성기"가 아니라, LLM이 판단하고 deterministic이 위험한 출력을 막는 구조다.

## Design Principles
- 판단은 LLM이 한다.
- 제한은 deterministic이 한다.
- source target, mount insertion, repair strategy, promotion recommendation은 LLM이 우선 결정한다.
- seam allowlist, build artifact 차단, malformed patch 차단, fresh run enforcement는 deterministic이 최종 gate로 남는다.
- LLM이 잘못 판단해도 바로 fallback으로 대체하지 않고, rejection reason을 다시 넣어 재시도시킨다.

## Recommended Approach
`LLM-first decision pipeline`으로 전환한다.

- `LLM Interpretation`
  - codebase map과 failure history를 읽고 실제 수정 seam 후보를 ranked decision으로 생성
- `LLM Planning`
  - target file, mount insertion strategy, repair scope를 구조화된 payload로 결정
- `Guardrail Filter`
  - seam 위반, build artifact, 과도한 edit scope를 판정
  - reject 시 deterministic이 대체 결정을 내리지 않고 LLM에 rejection reason을 돌려 재계획
- `LLM Patch / Edit`
  - patch 또는 file-level edit 제안 생성
  - malformed diff나 invalid target이면 error-aware retry 수행
- `LLM Repair Strategist`
  - run-level repair와 generator promotion recommendation 초안 생성
- `Promotion Gate`
  - 반복 횟수, fresh run, allowed ownership만 deterministic으로 확정

## Decision Ownership Split
### LLM-Owned Decisions
- target selection
- frontend mount insertion strategy
- run-level repair scope and file set
- generator promotion recommendation
- runtime repair patch proposal

### Deterministic Guardrails
- seam allowlist
- build/dist/node_modules/.venv 차단
- patch/apply validation
- maximum target count / ownership root restriction
- fresh run required after generator promotion
- export target filtering

## Execution Flow
1. `codebase_mapper`가 raw codebase map을 생성한다.
2. `write_llm_codebase_interpretation(...)`가 source-seam 우선 ranked candidates를 생성한다.
3. `write_llm_first_patch_proposal(...)`가 target file / repair scope / insertion strategy를 제안한다.
4. guardrail이 unsafe target을 reject한다.
5. reject reason이 있으면 LLM proposal 재시도 루프를 돈다.
6. `write_llm_patch_draft(...)`가 patch를 생성한다.
7. patch validation이 실패하면 raw fallback 대신 error-aware retry를 한 번 더 수행한다.
8. validation/smoke/runtime completion 실패 시 `LLM repair strategist`가 repair scope를 제안한다.
9. `promotion_judge`는 recommendation + recurrence count + site-local gate를 합쳐 최종 `run_only` / `generator_promoted`를 결정한다.
10. `generator_promoted`면 `generator_repair_request` artifact를 남기고 fresh run만 허용한다.

## Module Changes
### `chatbot/src/onboarding/codebase_mapper.py`
- LLM interpretation을 단순 설명이 아니라 source-seam ranking 용도로 강화
- build artifact를 절대 직접 추천하지 않도록 recovery와 validation 강화

### `chatbot/src/onboarding/patch_planner.py`
- deterministic target selection을 기본 경로에서 제거
- `llm proposal -> guardrail reject -> llm retry` 루프 추가
- patch draft malformed 시 `hard_fallback` 대신 structured retry 먼저 수행
- frontend mount insertion strategy를 LLM payload의 일부로 다룬다

### `chatbot/src/onboarding/recovery_planner.py`
- 분류 엔진에서 LLM repair recommendation normalizer로 축소
- site-local vs pipeline-generalizable 분류도 LLM recommendation을 우선 사용

### `chatbot/src/onboarding/orchestrator.py`
- 각 stage의 기본 경로를 LLM-first로 재배선
- rejection reason / retry reason / promotion recommendation artifact 기록
- generator promotion 시 `generator_repair_request`와 fresh-run policy를 유지

### `chatbot/src/onboarding/promotion_judge.py`
- threshold / fresh-run / ownership gate만 담당
- classification 해석의 중심은 제거

### `chatbot/src/onboarding/runtime_llm_repair.py`
- import repair 전용 느낌에서 runtime repair 공용 executor로 확장
- mount / router / auth bootstrap 관련 runtime evidence도 LLM에 전달 가능하게 함

### `chatbot/src/onboarding/framework_strategies.py`
- "strategy chooser"가 아니라 "target validator"에 가깝게 축소
- LLM이 고른 target이 seam 밖이면 reject reason만 생성

## Testing Strategy
테스트는 규칙 기반 정답 비교보다 아래를 검증한다.

- LLM proposal이 build artifact를 고르면 reject + retry가 되는가
- LLM이 `App.js`를 고르더라도 `<Routes>` 내부 삽입은 reject되고 재계획되는가
- `structure_summary` 같은 shape drift는 promotion 없이 recovered_llm으로 통과하는가
- same failure signature 2회에서만 generator promotion이 열리는가
- generator promotion은 `chatbot/src/onboarding` ownership과 fresh-run policy를 강제하는가
- runtime import repair는 canned repair보다 LLM repair를 먼저 시도하는가

## Success Criteria
- target selection 기본 경로가 LLM이 된다.
- deterministic code는 안전성 검증과 reject reason 생성만 담당한다.
- frontend mount 오류 같은 구조 문제에서 LLM 재시도가 실제 개선 경로로 동작한다.
- repeated pipeline bug는 generator promotion으로 이어지고, site-local issue는 run-level repair에 머문다.
- debug artifact만 봐도 LLM 판단, reject reason, retry reason, final gate result를 추적할 수 있다.

## Non-Goals
- deterministic guardrail 완전 제거
- source repository 전체 무제한 수정 허용
- generator promotion 후 기존 run artifact 재사용
- LLM이 테스트 없이 성공을 선언하게 만드는 구조
