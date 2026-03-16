# Generator Eval Design

## Goal

`Generator` 역할의 LLM 출력 품질을 `golden dataset + rule-based rubric`으로 평가하는 구조를 정의한다. 이 평가는 실제 생성 코드가 아니라, `proposed_files`와 `proposed_patches` 제안 품질을 검증하는 데 집중한다.

## Why

현재 onboarding agent는 `Generator` 제안을 실제 materialization에 반영할 수 있다. 따라서 이제 중요한 질문은 "연결되었는가"가 아니라 "제안 품질이 충분히 좋은가"다.

이 품질은 일반적인 unit test만으로는 판단할 수 없다. 이유는 아래와 같다.

- LLM 출력은 의미 품질을 봐야 한다.
- patch proposal은 정답 하나보다 허용/금지 경계가 중요하다.
- 잘못된 제안은 시스템 오류가 아니라 품질 저하로 나타난다.

따라서 deterministic 시스템 테스트와 별도로 `Generator` 전용 평가 체계가 필요하다.

## Core Decision

초기 평가는 `golden dataset + rule-based rubric`으로 간다.

- 사람 손으로 curated fixture를 만든다.
- 각 fixture는 입력 context와 기대 proposal을 가진다.
- 평가기는 실제 `Generator` 출력과 fixture를 비교한다.
- 첫 단계에서는 judge model을 붙이지 않는다.

이 방식은 해석 가능하고, 회귀 테스트에 적합하며, 실패 원인을 바로 읽을 수 있다.

## Fixture Format

fixture는 JSON 파일 하나가 하나의 케이스다.

권장 구조:

```json
{
  "id": "food-auth-and-frontend",
  "site": "food",
  "input": {
    "analysis": {
      "framework": {"backend": "django", "frontend": "react"},
      "auth": {
        "auth_style": "session_cookie",
        "login_entrypoints": ["backend/users/views.py:login"],
        "me_entrypoints": ["backend/users/views.py:me"],
        "signals": ["session_token", "request.COOKIES"]
      },
      "product_api": ["/api/products/"],
      "order_api": ["/api/orders/"],
      "frontend_mount_points": ["frontend/src/App.js"],
      "backend_entrypoints": [],
      "route_prefixes": []
    },
    "recommended_outputs": [
      "chat_auth",
      "order_adapter",
      "product_adapter",
      "frontend_patch"
    ]
  },
  "expected": {
    "proposed_files": [
      "files/backend/chat_auth.py",
      "files/backend/order_adapter_client.py",
      "files/backend/product_adapter_client.py"
    ],
    "proposed_patches": [
      "patches/frontend_widget_mount.patch"
    ]
  },
  "forbidden": [
    "food/backend/",
    "runtime/",
    "generated/"
  ],
  "notes": "food baseline should propose all four onboarding artifacts"
}
```

## Stored Data

fixture는 아래 위치에 둔다.

```text
chatbot/tests/onboarding/goldens/generator/
```

초기 fixture 세트:

- `food` 기본 케이스
- `bilyeo` 기본 케이스
- `ecommerce` 기본 케이스
- auth-only 케이스
- frontend-only 케이스
- ambiguous/partial evidence 케이스

## Evaluation Contract

`Generator` 실행 입력은 fixture의 `input`을 그대로 사용한다.

평가 대상 출력:

- `metadata.proposed_files`
- `metadata.proposed_patches`

필요 시 아래를 추가로 기록한다.

- `claim`
- `evidence`
- `risk`
- `next_action`

하지만 pass/fail 판정은 우선 proposal 집합으로만 계산한다.

## Rubric

각 케이스는 아래 규칙으로 채점한다.

- `missing_files`
- `extra_files`
- `missing_patches`
- `extra_patches`
- `forbidden_hits`

판정:

- 위 다섯 항목이 모두 비어 있으면 `pass`
- 하나라도 있으면 `fail`

추가 품질 신호:

- `proposal_count`
- `expected_count`
- `coverage_ratio`

그러나 초기 의사결정은 `pass/fail`과 diff summary 중심으로 본다.

## Forbidden Rules

금지 항목은 fixture마다 다를 수 있지만 기본 원칙은 같다.

- 원본 사이트 경로 직접 수정 제안 금지
- runtime workspace 경로 제안 금지
- generated report 경로 제안 금지
- 전체 코드 blob 또는 비정상 path 금지

즉 `Generator`는 항상 overlay artifact 경로만 제안해야 한다.

## Eval Output

평가 결과는 JSON으로 저장한다.

예시:

```json
{
  "id": "food-auth-and-frontend",
  "pass": false,
  "missing_files": ["files/backend/order_adapter_client.py"],
  "extra_files": [],
  "missing_patches": [],
  "extra_patches": [],
  "forbidden_hits": [],
  "actual": {
    "proposed_files": [
      "files/backend/chat_auth.py",
      "files/backend/product_adapter_client.py"
    ],
    "proposed_patches": [
      "patches/frontend_widget_mount.patch"
    ]
  }
}
```

## Eval Runner Flow

1. fixture 디렉터리 로드
2. 각 fixture마다 `Generator` role 실행
3. `proposed_files`, `proposed_patches` 추출
4. rubric 계산
5. 결과 JSON 생성
6. 요약 출력

## Non-Goals

이번 평가 설계의 비목표:

- judge model 기반 의미 평가
- patch body 자체의 semantic correctness 평가
- 실제 서버 실행 여부 평가
- full end-to-end onboarding quality 전체 점수화

이 평가는 `Generator proposal quality`만 본다.

## Next Step

다음 구현은 아래 순서가 적절하다.

1. fixture schema 정의
2. sample golden 3~5개 작성
3. rubric 함수 구현
4. eval runner 구현
5. pytest 기반 golden regression 추가
