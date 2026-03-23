# Framework Strategy Onboarding Design

## Goal
`Django/Flask/FastAPI + React/Vue` 조합에 대해 온보딩 서비스가 실제 통합 가능한 수준의 overlay를 자동 생성하고, runtime simulation과 smoke validation을 거쳐 export 가능한 patch까지 산출하도록 일반화한다.

## Problem
현재 파이프라인은 분석, 제안, overlay 파일 생성, runtime merge simulation, smoke/export 흐름은 갖추고 있지만 실제 통합 경계가 약하다.

주요 한계는 다음과 같다.

- backend auth 파일은 생성하지만 실제 URL wiring이 자동 보장되지 않는다.
- frontend widget은 mount patch를 생성해도 실제 auth bootstrap/tool endpoint 연동 계약이 약하다.
- order/product adapter는 생성되지만 tool execution 경로와 공통 registry로 연결되지 않는다.
- smoke는 사이트별 응답 계약을 충분히 반영하지 못하고 framework-specific wiring 성공 여부를 직접 검증하지 않는다.
- LLM proposal과 deterministic generator 사이에 공통 integration contract가 없다.

## Recommended Approach
공통 파이프라인은 유지하고, 실제 통합 지점만 framework strategy layer로 분리한다.

- 공통 파이프라인:
  - analysis
  - planning
  - generation
  - apply approval
  - runtime simulation
  - validation
  - export
- strategy layer:
  - `BackendIntegrationStrategy`
  - `FrontendIntegrationStrategy`

공통 contract는 다음 네 가지다.

- backend chat auth contract
- frontend widget bootstrap contract
- tool adapter registry contract
- smoke validation contract

## Why Strategy Layer
완전 범용 LLM patching만으로는 재현성과 안정성이 부족하다. 반대로 사이트별 하드코딩은 확장성이 없다. 따라서 framework마다 "어디를 어떻게 고치는가"만 전략으로 분리하고, 나머지 pipeline과 artifact contract는 공유하는 구조가 가장 현실적이다.

## Backend Design

### Backend strategy interface
각 전략은 최소한 다음 책임을 가진다.

- auth handler target 후보 해석
- route registration target 후보 해석
- `chat_auth.py` 생성 위치와 import path 결정
- 실제 route wiring patch 생성
- adapter/tool registry wiring patch 생성
- smoke probe용 backend endpoint metadata 제공

### Django strategy
- `urls.py` 또는 project urlconf에 `chat_auth` endpoint를 include/path로 연결
- 필요 시 `backend/<app>/views.py` 또는 별도 module import patch 생성
- 세션 쿠키 기반 auth state를 재활용해 `/api/chat/auth-token` contract 보장

### Flask strategy
- blueprint 생성 파일 또는 app factory 탐지
- `register_blueprint()` patch 생성
- session 기반 auth state lookup을 이용한 `/api/chat/auth-token` contract 보장

### FastAPI strategy
- router module 생성 또는 기존 router module include
- `include_router()` patch 생성
- cookie/token lookup 기반 `/api/chat/auth-token` contract 보장

### Backend output contract
backend strategy가 성공적으로 생성해야 하는 것은 다음이다.

- `files/backend/chat_auth.py`
- 선택적 `files/backend/tool_registry.py` 또는 이에 준하는 wiring artifact
- framework-specific route wiring patch
- smoke에 필요한 endpoint metadata

## Frontend Design

### Frontend strategy interface
각 전략은 다음 책임을 가진다.

- mount target 후보 해석
- widget import path 계산
- 실제 mount patch 생성
- auth bootstrap fetch wiring 제안
- widget runtime config 제공

### React strategy
- `App`, layout, route shell 등 mount 후보 선택
- `SharedChatbotWidget` import 추가
- JSX mount 삽입
- `/api/chat/auth-token` bootstrap fetch와 runtime config 연결

### Vue strategy
- `.vue` SFC import 또는 local component registration patch 생성
- template/script block 모두 처리 가능해야 함
- `SharedChatbotWidget` usage 삽입과 bootstrap config 연결

### Frontend widget contract
위젯은 placeholder가 아니라 최소한 다음 경계를 가져야 한다.

- bootstrap endpoint: `/api/chat/auth-token`
- authenticated / unauthenticated 상태 처리
- tool endpoint 또는 backend bridge config
- site id / runtime config 주입
- mount success를 evaluator가 검증 가능해야 함

## Tool/Adapter Design

### Current gap
`product_adapter_client.py`, `order_adapter_client.py` 생성만으로는 chatbot execution path에 연결되지 않는다.

### Proposed contract
- adapter는 공통 method set을 제공한다.
  - product: `list_products`, `get_product`
  - order: `list_orders`, `get_order`, `submit_order_action`
- backend 쪽에 tool registry wiring artifact를 추가한다.
- registry는 detected capabilities에 따라 활성 tool set을 구성한다.
- smoke와 evaluator는 registry wiring artifact 존재 여부와 adapter import 가능성을 검증한다.

## Manifest and Analysis Extensions

### Analysis additions
manifest `analysis`에 다음 정보를 보강한다.

- `backend_strategy`: `django` | `flask` | `fastapi` | `unknown`
- `frontend_strategy`: `react` | `vue` | `unknown`
- `backend_route_targets`: route wiring 후보 목록
- `frontend_mount_targets`: mount patch 후보 목록
- `tool_adapter_targets`: adapter wiring 후보 목록

### Generated artifact additions
manifest `generated_files`, `patch_targets`, `frontend_artifacts` 외에 strategy provenance를 포함한다.

예시:

- `integration.backend.strategy`
- `integration.frontend.strategy`
- `integration.tool_registry.enabled_tools`

## Validation Design

### Runtime simulation
기존 runtime copy + patch merge simulation은 유지한다.

### Backend evaluator
다음을 확인한다.

- `chat_auth.py` 존재
- route wiring patch가 simulation workspace에 적용되었는지
- `/api/chat/auth-token` endpoint contract가 smoke와 일치하는지
- adapter/tool registry wiring artifact 존재 여부

### Frontend evaluator
다음을 확인한다.

- widget file 존재
- 실제 import/use patch 반영 여부
- bootstrap config 존재 여부
- React/Vue mount contract 만족 여부

### Smoke validation
framework-aware probe plan을 사용한다.

- login
- chat-auth-token
- product-api
- order-api

필요 시 auth header/cookie propagation 규칙은 backend strategy가 제공한다.

## Failure Model
성공을 주장하기 전에 다음 중 하나로 분류한다.

- `llm`
- `recovered_llm`
- `hard_fallback`

다음 상황은 structural failure로 간주한다.

- backend route wiring target을 찾지 못함
- frontend mount target을 찾지 못함
- adapter registry target을 찾지 못함
- framework unsupported

이 경우 patch를 억지로 생성하지 않고 human review로 넘긴다.

## Success Criteria

- Django/Flask/FastAPI 프로젝트에서 `/api/chat/auth-token` route wiring patch가 자동 생성된다.
- React/Vue 프로젝트에서 widget mount patch가 자동 생성된다.
- product/order adapter가 backend tool execution 경로와 연결된다.
- runtime simulation에서 generated files + patches가 적용된다.
- backend/frontend evaluator가 framework-aware contract를 검증한다.
- smoke가 login -> chat auth -> product -> order 호출을 실제로 수행한다.
- export patch가 runtime diff 기준으로 생성된다.

## Non-Goals

- Express/Nest/Next.js 지원
- browser E2E 자동화
- unsupported framework에 대한 무제한 self-healing patching
- production deploy 자동화
