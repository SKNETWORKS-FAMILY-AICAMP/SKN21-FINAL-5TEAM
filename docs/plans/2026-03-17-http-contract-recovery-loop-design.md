# HTTP Contract Recovery Loop Design

## Goal
브라우저 상호작용 로그인 이후 발생하는 HTTP contract mismatch를 자동으로 분류하고, 안전한 범위의 recovery 수정 후 재검증하는 온보딩 복구 루프를 추가한다.

## Scope
이번 1차 범위는 다음 mismatch만 자동 복구 대상으로 둔다.

- login route mismatch
- login payload mismatch
- csrf requirement mismatch
- cookie propagation mismatch
- chat auth response mismatch
- product schema mismatch
- order schema mismatch
- route target mismatch
- mount target mismatch

다음은 자동 복구 대상이 아니다.

- 브라우저 로그인 자동 수행
- OAuth / SSO / 외부 리다이렉트 인증
- 근거 없는 새 endpoint 발명
- 대규모 source rewrite

## Problem
현재 파이프라인은 strategy-aware generation과 validation까지 수행하지만, 사이트가 예상한 HTTP contract와 조금만 달라도 검증 실패 후 human review로 바로 빠질 가능성이 높다.

예를 들면 다음과 같다.

- `/api/login` 대신 `/api/auth/login` 사용
- body 키가 `username/password`가 아니라 `email/password`
- CSRF 토큰을 먼저 받아야 함
- login cookie 이름이 `session`이 아니라 `sessionid`
- `/api/chat/auth-token` 응답이 `token` 또는 `data.access_token`
- 상품/주문 응답 key가 `items/orders`가 아니라 `results/data/list`

이런 종류는 완전 구조적 실패가 아니라 "contract mismatch"에 가깝고, deterministic correction으로 복구할 수 있다.

## Recommended Architecture
`Diagnostician + Recovery Planner + Deterministic Fixer + Re-validator` 구조로 간다.

### Diagnostician
- 입력:
  - smoke results
  - smoke context
  - backend/frontend evaluator 결과
  - merge simulation 결과
  - strategy metadata
- 출력:
  - failure classification
  - recovery 가능 여부
  - candidate corrections

### Recovery Planner
- Diagnostician이 낸 가설을 recovery payload로 정규화한다.
- 복구 대상은 probe plan, expected schema, target candidate selection, adapter extractor config로 제한한다.

### Deterministic Fixer
- recovery payload만 보고 실제 artifact를 제한적으로 수정한다.
- source tree 직접 수정은 하지 않는다.
- 수정 대상:
  - smoke probe url/header/body/uses/exports/expected keys
  - backend route target selection metadata
  - frontend mount target selection metadata
  - adapter response extractor metadata

### Re-validator
- recovery 적용 후 smoke/evaluator를 재실행한다.
- retry budget 내에서만 반복한다.

## Failure Taxonomy

### Auth
- `login_route_mismatch`
- `login_payload_mismatch`
- `csrf_requirement_mismatch`
- `cookie_propagation_mismatch`
- `chat_auth_response_mismatch`

### Domain schema
- `product_schema_mismatch`
- `order_schema_mismatch`

### Integration target
- `route_target_mismatch`
- `mount_target_mismatch`

### Non-recoverable in phase 1
- `interactive_auth_required`
- `oauth_redirect_required`
- `unsupported_framework_contract`

## Recovery Payload Contract
새 recovery artifact는 structured JSON이다.

예시 필드:

- `classification`
- `confidence`
- `should_retry`
- `proposed_probe_updates`
- `proposed_target_overrides`
- `proposed_schema_overrides`
- `blocking_reason`

### Probe updates example
```json
{
  "step_id": "login",
  "url": "http://127.0.0.1:8000/api/auth/login",
  "body": {
    "email": "{{probe.credentials.username}}",
    "password": "{{probe.credentials.password}}"
  }
}
```

### Schema overrides example
```json
{
  "step_id": "product-api",
  "expects": {
    "json_keys": ["results"]
  },
  "exports": {
    "product.first_item": "json.results[0]"
  }
}
```

## Artifact Layout

### New artifacts
- `reports/recovery-classification.json`
- `reports/recovery-plan.json`
- `reports/recovery-attempts.json`
- `reports/recovered-smoke-plan.json`

### Existing artifacts reused
- `reports/smoke-results.json`
- `reports/smoke-summary.json`
- `reports/smoke-context.json`
- `reports/backend-evaluation.json`
- `reports/frontend-evaluation.json`

## Deterministic Fix Rules

### Allowed
- replace login URL from known route prefixes
- rename auth body keys using known aliases
- add CSRF header/cookie propagation if probe result proves requirement
- switch response export path between known aliases
- switch mount/route target to another detected candidate

### Forbidden
- add brand new endpoint with no evidence
- invent new auth mode
- rewrite arbitrary user source files
- continue retrying after confidence drops or retry budget exhausted

## Data Flow

1. generation/apply/validation runs as usual
2. smoke or evaluator failure occurs
3. Diagnostician classifies mismatch
4. Recovery Planner emits structured recovery payload
5. Deterministic Fixer writes recovered smoke plan / target overrides
6. smoke + evaluator rerun
7. if pass: mark `recovered_llm`
8. if fail and retry budget exhausted: `human_review_required`

## Retry Policy

### Budget
- default max recovery attempts: 2

### Stop immediately when
- classification is non-recoverable
- confidence < threshold
- proposed update exceeds safe bounds
- same signature repeats after one correction

## Success Criteria
- common HTTP mismatch cases no longer go directly to human review
- recovery actions are auditable and deterministic
- retry count is bounded
- final artifacts preserve provenance: `llm`, `recovered_llm`, `hard_fallback`

## Non-Goals
- interactive browser automation
- CAPTCHA handling
- OAuth callback orchestration
- autonomous code rewriting beyond configured artifact surfaces
