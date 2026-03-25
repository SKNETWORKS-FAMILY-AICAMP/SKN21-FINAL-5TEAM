# Onboarding Repair Eval Retry Agent Design

## Goal
onboarding generation이 첫 시도에 완벽히 성공하지 않는다는 전제를 받아들이고, 실패를 분류한 뒤 run 산출물을 먼저 자동 수리하고, 같은 실패가 반복될 때만 generator 본체를 수정하는 이중 루프 구조를 도입한다.

## Problem
현재 onboarding 파이프라인은 generation, validation, smoke, runtime completion, recovery artifact를 이미 어느 정도 갖추고 있지만, 실패를 "한 번의 run 실패"로 처리하는 경향이 강하다.

이 구조에는 두 가지 한계가 있다.

- run 산출물 수준에서 고칠 수 있는 문제와 generator 버그를 명확히 구분하지 못한다.
- 같은 실패가 반복돼도 이를 generator 개선 신호로 승격시키는 일관된 기준이 없다.

실제 recent run들에서 드러난 문제는 이 경계를 잘 보여준다.

- malformed LLM payload / malformed unified diff
- frontend mount patch가 React Router 규칙을 깨는 문제
- build 산출물을 mount target으로 오탐하는 문제
- 개별 사이트 seam에만 국한된 auth/order/frontend wiring mismatch

즉 지금 필요한 것은 "무조건 한 번에 맞추는 생성기"가 아니라, 실패를 근거 있게 고치고 재실행하면서 구조적 버그를 본체로 승격시키는 운영 모델이다.

## Recommended Approach
`dual-loop onboarding repair agent`를 도입한다.

- 1차 루프: run 산출물과 runtime workspace만 수정하는 `Run Repair Agent`
- 2차 루프: 같은 failure signature가 2회 반복되면 `Generator Repair Agent`가 onboarding 본체를 수정

핵심 원칙은 다음과 같다.

- 원본 사이트는 최소 침습 원칙을 따른다.
- 원본 수정은 seam 범위 안에서만 허용한다.
- generator 본체 수정은 반복되는 파이프라인 버그에 한해서만 허용한다.
- generator 수정의 효능은 반드시 새 run id에서 재검증한다.

## Architectural Overview
구성 요소는 다섯 개다.

1. `Execution Agent`
- 기존 onboarding run 실행
- generated, runtime workspace, validation report, smoke/runtime completion report 생성

2. `Evaluator Agent`
- backend/frontend/smoke/runtime completion 결과를 읽고 failure signature를 정규화
- 직전 시도 대비 무엇이 개선됐는지 delta를 기록

3. `Run Repair Agent`
- `generated/` 와 `runtime/<site>/<run-id>/workspace`만 수정
- 대상은 seam 범위 patch와 generated artifact에 한정
- generator 본체는 수정하지 않음

4. `Promotion Judge`
- 같은 failure signature가 2회 반복됐는지 판정
- site-local issue인지 pipeline-generalizable bug인지 구분

5. `Generator Repair Agent`
- `chatbot/src/onboarding` 본체와 관련 테스트를 수정
- 수정 후 반드시 새 run에서 회귀 검증

## Failure Signature Model
실패는 자유 텍스트가 아니라 정규화된 signature로 다룬다.

기본 형식:

- `stage`
- `class`
- `detail`

예시:

- `frontend_mount_violation:routes_child_violation`
- `frontend_target_detection:build_artifact_selected`
- `patch_proposal:invalid_target_selection`
- `patch_draft:invalid_patch_format`
- `codebase_interpretation:invalid_llm_payload.structure_summary_type`
- `runtime_stack:health_connection_refused`
- `smoke:login_failed`
- `runtime_completion:auth_bootstrap_failed`

이 모델의 목적은 두 가지다.

- 서로 다른 문제를 같은 failure로 오판하지 않기
- 반복 횟수를 기계적으로 누적해 generator 승격 여부를 판단하기

## Promotion Rule
승격 규칙은 단순하고 보수적으로 둔다.

- 첫 실패:
  - `Run Repair Agent`가 run artifact만 고친다.
- 같은 failure signature가 2회 반복:
  - `Promotion Judge`가 generator 수정 대상으로 승격한다.
- generator 수정 후:
  - 반드시 새 run id로 다시 실행한다.
- 새 failure signature가 나오면:
  - 기존 실패와 분리된 새 이슈로 본다.

중요한 제한:

- site-local seam mismatch는 generator 승격 대상이 아니다.
- build 산출물 오탐, invalid shape drift, 반복 mount patch bug 같은 pipeline-generalizable 문제만 generator 승격 대상으로 본다.

## Seam-Limited Original Site Modification
원본 사이트 수정은 seam만 허용한다.

허용 seam:

- `auth seam`
  - `/api/chat/auth-token` 같은 bridge endpoint 연결
- `frontend mount seam`
  - 앱 셸/라우터 바깥 mount 지점에 widget host contract와 web component 삽입
- `order bridge seam`
  - `list_orders`, `get_order_status`, `cancel`, `refund`, `exchange` 로의 매핑 연결

비허용 영역:

- 원본 비즈니스 로직 일반 수정
- 페이지 구조 전면 개편
- 인증 체계 자체 교체
- build 산출물 직접 패치 고착화

이 원칙은 "원본 무수정"이 아니라 "원본 최소 침습"을 목표로 한다.

## Repair Scope Boundaries
### Run Repair Agent
수정 가능:

- `generated/<site>/<run-id>/...`
- `runtime/<site>/<run-id>/workspace/...`
- seam 범위 patch / generated file / runtime wiring

수정 불가:

- `chatbot/src/onboarding` 본체
- 원본 사이트 전체 비즈니스 로직

### Generator Repair Agent
수정 가능:

- `chatbot/src/onboarding/...`
- 관련 테스트
- 필요 시 shared widget/runtime contract code

수정 불가:

- 개별 사이트 일반 비즈니스 로직
- seam 밖 원본 파일

## Execution Loop
최종 루프는 다음 순서로 동작한다.

1. `Execution Agent`가 onboarding run 실행
2. `Evaluator Agent`가 failure signature와 evaluation delta 작성
3. 실패 시 `Run Repair Agent`가 run artifact만 수정
4. 같은 run의 recovery evaluation 또는 recovery run 재실행
5. 같은 signature가 2회 반복되면 `Promotion Judge`가 승격
6. `Generator Repair Agent`가 onboarding 본체 수정
7. 새 run id로 재실행하여 재발 여부 확인

## Stop Conditions
성공:

- backend/frontend validation 통과
- smoke 통과
- runtime completion 통과 또는 허용된 probe policy 충족

중단:

- seam 밖 수정이 필요한 경우
- 보안/정책상 위험한 수정이 필요한 경우
- generator를 2회 이상 고쳤는데 같은 계열 실패가 유지되는 경우
- 아키텍처 문제로 판단되는 경우

이 경우 human review로 넘긴다.

## Memory And Artifacts
각 run은 다음 정보를 남긴다.

- `failure_signature`
- `attempt_index`
- `repair_scope`
- `files_touched`
- `evaluation_delta`
- `promotion_decision`

또한 별도 반복 실패 메모리를 유지한다.

- key: `site + failure_signature`
- value:
  - 누적 횟수
  - 마지막 repair scope
  - 마지막 결과
  - generator 승격 여부

## Success Criteria
- onboarding failure가 run-level issue와 generator-level bug로 분리돼 기록된다.
- 첫 실패는 run artifact만 수정한다.
- 같은 failure signature 2회 반복 시 generator 승격이 자동으로 일어난다.
- generator 수정은 새 run id에서 재검증된다.
- seam 밖 원본 수정은 금지된다.
- recovery/evaluation/promotion 결과가 artifact로 남아 후속 분석이 가능하다.

## Non-Goals
- 무제한 self-healing
- 원본 사이트 완전 무수정
- 한 루프에서 여러 failure class 동시 수정
- generator 수정 후 기존 run artifact를 덮어써 성공처럼 보이게 만드는 것

## Assumptions
- 반복 failure 판단에 필요한 run history를 읽을 수 있다.
- 현재 `recovery-plan`, `failure_classifier`, `runtime_completion`, `role_runner`, `run_resume` 구조를 확장하는 것이 신규 파이프라인을 따로 만드는 것보다 유리하다.
- onboarding generator 본체는 `chatbot/src/onboarding` 아래 모듈을 중심으로 수정한다.
