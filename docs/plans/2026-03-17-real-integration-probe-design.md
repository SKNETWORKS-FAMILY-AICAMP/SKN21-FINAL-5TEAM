# Real Integration Probe Design

## Goal
기존 fake smoke scaffold를 실제 runtime integration probe pipeline으로 교체해 `login`, `chat token`, `product`, `order` 네 가지를 실제 호출 기반으로 검증한다.

## Problem
현재 smoke는 `overlay_generator.py`가 `echo login-ok`, `echo product-api-ok` 같은 shell script를 생성하고, `smoke_runner.py`는 그 script 실행 결과만 수집한다. 이 구조는 실행 파이프라인 자체는 검증하지만 실제 사이트 통합 상태는 거의 검증하지 못한다.

구체적으로 아직 검증되지 않는 것은 다음과 같다.

- 로그인 쿠키/세션이 실제로 획득되는지
- chat auth token endpoint가 실제로 발급되는지
- product endpoint가 실제 응답을 반환하는지
- order endpoint가 실제 응답을 반환하는지
- step 간 상태 전달(cookie/token/context)이 동작하는지

## Recommended Approach
`Runtime integration probe pipeline`으로 교체한다.

- smoke plan은 더 이상 shell script 목록이 아니다.
- 각 step은 structured HTTP probe spec이다.
- probe runner가 runtime workspace 기준으로 실제 HTTP 요청을 실행한다.
- `login -> chat token -> product -> order` 순서로 상태를 전달한다.
- 실패 시 recovery agent가 probe 수정 시도, 그래도 실패면 `hard_fallback`으로 기록한다.

## Probe Contract

### ProbeStep required fields
- `id`
- `category`
- `kind`
- `method`
- `url`
- `expects`

### Optional fields
- `headers`
- `body`
- `query`
- `timeout_seconds`
- `required`
- `exports`
- `uses`

### Example
```json
{
  "id": "chat-auth-token",
  "category": "auth",
  "kind": "http",
  "method": "POST",
  "url": "http://127.0.0.1:8000/api/chat/auth-token",
  "headers": {
    "Cookie": "{{login.cookies}}"
  },
  "expects": {
    "status": 200,
    "json_keys": ["authenticated", "access_token"]
  },
  "exports": {
    "access_token": "json.access_token"
  },
  "uses": ["login.cookies"]
}
```

## Runtime State Passing
probe runner는 step 결과에서 runtime context를 축적한다.

### Stored context examples
- `login.cookies`
- `login.csrf_token`
- `chat_auth.access_token`
- `product.first_product_id`
- `order.first_order_id`

후속 step은 `{{...}}` 템플릿으로 이전 step 결과를 참조할 수 있다.

## Responsibilities

### LLM
- endpoint 후보, auth/header/cookie 전략 제안
- probe 순서와 exported state 제안
- 실패 로그를 보고 recovery probe 수정안 제안

### Deterministic
- HTTP request 실행
- timeout/retry/serialization
- response code/json parsing
- expected status/json key 검증
- state extraction
- 결과 artifact 기록

## Probe Sequence For First Milestone

### 1. Login Probe
- 목적: 인증 상태 획득
- 출력: cookie/session context

### 2. Chat Token Probe
- 목적: chat auth token 획득
- 입력: login output
- 출력: bearer/access token

### 3. Product Probe
- 목적: 실제 product endpoint 응답 검증
- 입력: optional auth context
- 출력: product id or first item context

### 4. Order Probe
- 목적: 실제 order endpoint 응답 검증
- 입력: auth context
- 출력: order id or first item context

## Recovery Model
probe plan/result source는 다음 셋 중 하나다.

- `llm`
- `recovered_llm`
- `hard_fallback`

### Recovery can do
- header/cookie name normalization
- method/url/body small corrections
- response key expectation adjustment within safe bounds

### Recovery must not do
- source code mutation
- silent endpoint invention with no evidence
- skipping required probes and still reporting pass

## Artifacts

### Replaced / extended
- `tests.smoke` in manifest now stores structured probe specs
- `reports/smoke-results.json` stores per-step request/response summary
- `reports/smoke-summary.json` still stores rollup

### New optional artifact
- `reports/smoke-context.json`
  - exported runtime state for debugging

## Agent Topology

### Controller
소유 파일:
- `chatbot/src/onboarding/orchestrator.py`

책임:
- probe execution stage 연결
- smoke summary/result wiring

### Probe Contract Agent
소유 파일:
- `chatbot/src/onboarding/smoke_contract.py`
- `chatbot/src/onboarding/overlay_generator.py`

책임:
- structured probe schema
- default probe plan generation

### Probe Runner Agent
소유 파일:
- `chatbot/src/onboarding/smoke_runner.py`

책임:
- HTTP execution
- state passing
- result summary writing

### Recovery Agent
소유 파일:
- 필요 시 새 `smoke_recovery.py`

책임:
- probe failure normalization/retry support

## Success Criteria
- fake echo shell scripts가 필수 경로에서 제거된다.
- `login`, `chat token`, `product`, `order` 네 가지가 모두 실제 호출 기반으로 검증된다.
- probe 결과가 request/response summary와 함께 artifact로 남는다.
- step 간 상태 전달이 작동한다.
- `llm/recovered_llm/hard_fallback` provenance가 보존된다.

## Non-Goals
- full browser E2E
- visual testing
- self-healing infinite edit loop
- 실제 source tree 자동 수정
