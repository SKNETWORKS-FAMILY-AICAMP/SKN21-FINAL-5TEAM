# Order CS Web Component Completion Design

**Date:** 2026-03-22

**Goal:** `chatbot/frontend/shared_widget`의 기존 React 기반 주문 CS UI와 LangGraph interrupt/actionUI 흐름을 유지한 채, 어떤 host 프레임워크에도 `<order-cs-widget>` 하나로 붙일 수 있는 완성형 web component 위젯 플랫폼을 만든다.

---

## 1. Problem

현재 코드는 중간 단계다.

- `chatbot/frontend/shared_widget` 아래에 공용 UI 소스는 있다.
- onboarding은 host site에 `/widget.js` 로더와 `<order-cs-widget>` mount patch를 생성한다.
- `/api/chat/auth-token` 같은 bridge contract도 정의되어 있다.

하지만 실제 배포 가능한 widget 본체는 아직 없다.

- `customElements.define("order-cs-widget", ...)` 구현이 없다.
- 서버는 브라우저용 번들이 아니라 raw `widget-entry.ts`를 사실상 `widget.js`처럼 가리킨다.
- host site는 `<order-cs-widget>`를 붙여도 브라우저에서 실제 custom element가 등록되지 않는다.

따라서 현재 시스템은 “위젯을 붙일 자리와 계약은 있음” 수준이고, “완성된 위젯을 붙여 실제로 동작함”까지는 닫히지 않았다.

---

## 2. Non-Goals

이번 범위에서 하지 않을 것:

- host site 프레임워크별 네이티브 챗 UI 재구현
- `order_cs` 범위를 넘는 모든 actionUI 일반화
- onboarding agent가 위젯 React 본체를 생성하도록 유지
- 기존 LangGraph interrupt 계약 재설계

이번 범위는 `order_cs` 전용 위젯 완성과 attach pipeline 재정의에 한정한다.

---

## 3. User Experience

사용자는 generated site의 어느 페이지에서든 우하단 floating launcher를 본다.

위젯을 열면 다음 순서로 동작한다.

1. host 페이지가 `widget.js`를 로드한다.
2. 브라우저가 `<order-cs-widget>` custom element를 등록한다.
3. 위젯이 generated site의 `/api/chat/auth-token`으로 토큰 bootstrap을 수행한다.
4. 위젯이 챗봇 서버 `/api/v1/chat/stream`에 연결한다.
5. 일반 대화는 채팅 메시지로 표시된다.
6. 주문 목록, 선택, 확인, 옵션 교체 같은 actionUI는 채팅 메시지 아래 카드/폼 UI로 표시된다.
7. 사용자가 버튼이나 선택을 누르면 위젯이 구조화된 `resume_payload`를 보내 LangGraph interrupt를 재개한다.

UX는 “채팅 + actionUI 혼합형”으로 유지한다.

---

## 4. Architecture

구조는 네 층으로 나눈다.

### 4.1 Shared React UI Layer

기존 React UI를 그대로 재사용한다.

핵심 파일:

- `chatbot/frontend/shared_widget/ChatbotWidget.tsx`
- `chatbot/frontend/shared_widget/chatbotfab.tsx`
- `chatbot/frontend/shared_widget/OrderListUI.tsx`
- `chatbot/frontend/shared_widget/ProductListUI.tsx`
- `chatbot/frontend/shared_widget/ReviewFormUI.tsx`
- `chatbot/frontend/shared_widget/UsedSaleFormUI.tsx`

이 레이어는 다음을 계속 담당한다.

- 메시지 렌더링
- 주문 목록 / 상품 목록 / 확인 / 선택형 actionUI 렌더링
- `resume_payload` 전송
- `ui_payload`, `ui_action_required`, `awaiting_interrupt`, `interrupts` 해석

### 4.2 Web Component Wrapper Layer

새 wrapper가 React UI를 custom element 내부에서 실행한다.

새 역할:

- `customElements.define("order-cs-widget", ...)`
- element mount/unmount lifecycle
- Shadow DOM 기본 사용
- host contract 읽기
- attribute override 적용
- React root 생성

중요한 점은 host 페이지가 React를 몰라도 된다는 것이다. React는 widget 내부 구현일 뿐이고, 외부 계약은 브라우저 표준 custom element다.

### 4.3 Widget Bundle / Serve Layer

챗봇 서버는 브라우저가 바로 실행할 수 있는 실제 `widget.js`를 서빙한다.

즉:

- raw `.ts` 파일 직접 반환 금지
- 빌드 산출물 `dist/widget.js` 반환
- 서버 시작 후 산출물 없으면 명시적 오류 또는 404

### 4.4 Onboarding Attach Layer

onboarding agent는 더 이상 위젯 구현자가 아니라 attach installer다.

해야 할 일:

- host contract 삽입
- `widget.js` bootstrap script 삽입
- `<order-cs-widget>`를 안전한 위치에 mount
- generated backend에 `/api/chat/auth-token` bridge 생성
- 기본 노출 정책은 “모든 페이지 우하단 floating launcher”

하지 않을 일:

- widget React 코드 생성
- custom element 본체 생성
- site별 프론트 전용 챗 UI 구현

---

## 5. ActionUI / Interrupt Model

`actionUI`는 새로 설계하지 않는다. 기존 interrupt contract를 재사용한다.

기존 흐름:

- 도구가 `interrupt()`로 사용자 선택 또는 확인을 요구한다.
- API layer가 `pending_interrupt`, `ui_action_required`, `ui_payload`를 SSE/응답으로 내린다.
- 프론트 위젯은 이를 actionUI로 렌더링한다.
- 사용자가 선택하면 구조화된 `resume_payload`를 다시 보낸다.
- 서버는 `Command(resume=...)`로 그래프를 재개한다.

이번 범위에서는 이 계약을 `order_cs`에 대해 유지한다.

지원 대상 actionUI:

- `show_order_list`
- `confirm_order_action`
- `show_product_list`
- 옵션 선택 계열 (`new_option_id`, `selected_option_id`)
- 필요 시 주소/사유 입력 계열

정책:

- `cancel`, `refund`, `exchange`는 최종 실행 전에 확인 단계를 둔다.
- `resume_payload`는 자연어가 아니라 구조화 payload를 사용한다.

---

## 6. Host Contract

위젯은 두 경로로 초기화 설정을 읽는다.

1. `globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__`
2. custom element attribute override

기본 contract 필드:

- `chatbotServerBaseUrl`
- `authBootstrapPath`
- `widgetBundlePath`
- `widgetElementTag`
- `mountMode`

attribute는 debugging/override용으로 둔다.

예:

- `chatbot-server-base-url`
- `auth-bootstrap-path`
- `mount-mode`

우선순위는 attribute > global contract > default 순서다.

---

## 7. Styling / Isolation

기본 렌더링은 Shadow DOM으로 한다.

이유:

- host 페이지 전역 CSS 충돌 완화
- 위젯 내부 스타일 격리
- 다른 프레임워크/디자인 시스템과 공존 가능성 상승

다만 예외 상황을 위해 light DOM fallback 여지는 남긴다. 기본 정책은 Shadow DOM이다.

---

## 8. Build Strategy

shared widget는 브라우저용 단일 엔트리로 빌드한다.

권장 구조:

- `widget-entry.ts` 또는 새 `web-component.tsx`를 실제 browser entry로 사용
- bundle 안에 React, renderer, transport, styles 포함
- 출력 경로는 `chatbot/frontend/shared_widget/dist/widget.js`

이 번들은 다음을 포함해야 한다.

- custom element registration
- host contract resolution
- React root mount
- `bootstrapSharedWidgetAuth`
- `streamSharedChatResponse`
- `chatbotfab` 기반 actionUI renderer

---

## 9. Server Changes

서버는 `/widget.js`를 다음 의미로 제공해야 한다.

- “브라우저가 실행 가능한 완성 widget bundle”

필수 변경:

- `WIDGET_BUNDLE_PATH`를 raw source가 아닌 build artifact로 전환
- `FileResponse`는 artifact만 반환
- artifact가 없을 때 오류를 감추지 않음

선택:

- startup check로 artifact 존재 보장
- dev mode에서는 번들 재생성 흐름 제공

---

## 10. Onboarding Changes

`frontend_patch` 의미를 재정의한다.

이전 의미:

- 위젯 생성 + mount patch에 가까운 중간 상태

새 의미:

- 완성된 공용 widget를 host runtime에 연결하는 attach patch

planner / generator / evaluator / smoke 변경 방향:

- planner: `frontend_patch`를 widget attach task로 취급
- generator: host contract, script bootstrap, mount patch, auth-token bridge 생성
- evaluator: generated site 내 widget 본체가 아니라 attach contract 존재 여부 검증
- smoke: widget bundle load + auth bootstrap + chat stream 연결 검증

---

## 11. Validation Strategy

검증은 세 층으로 한다.

### 11.1 Unit

- custom element registration
- contract merge
- Shadow DOM mount
- `resume_payload` serialization
- ui_payload -> actionUI renderer mapping

### 11.2 Integration

- `/widget.js` route가 실제 artifact를 반환
- generated site의 `/api/chat/auth-token`이 401/200 규약을 만족
- widget가 bootstrap 후 stream endpoint에 연결

### 11.3 End-to-End

최소 `order_cs` 시나리오:

1. 위젯 open
2. chat auth bootstrap
3. 주문 조회
4. `show_order_list` actionUI 노출
5. order select -> `resume_payload`
6. `confirm_order_action` 노출
7. 승인 -> cancel/refund/exchange 액션 진행

---

## 12. Risks

### 12.1 Existing UI Not Yet Bundle-Ready

shared widget 코드는 존재하지만, 바로 custom element로 감쌀 때 브라우저/번들링 가정이 맞지 않을 수 있다.

대응:

- browser entry를 명시적으로 분리
- unit test로 custom element registration 보장

### 12.2 CSS / Overlay Issues

launcher, portal, modal류 UI는 Shadow DOM에서 일부 레이아웃 이슈가 생길 수 있다.

대응:

- overlay root를 widget shadow 내부로 일관되게 한정
- 필요한 경우 fallback 옵션 마련

### 12.3 Runtime Host Assumptions

host 페이지마다 `main`, router boundary, hydration 구조가 다르다.

대응:

- onboarding mount policy를 “모든 페이지 우하단 launcher” 기준으로 단순화
- 금지 영역(`Routes` 내부 등)만 피하는 규칙 유지

### 12.4 Widget / Chat Server Version Drift

host contract와 widget bundle API가 어긋날 수 있다.

대응:

- contract 필드를 명시적으로 고정
- evaluator/smoke에서 contract presence 체크

---

## 13. Decision Summary

최종 결정:

- `order_cs` 범위만 우선 완성
- `chat + actionUI` 혼합형 유지
- 구조화 `resume_payload` 사용
- `cancel/refund/exchange`는 확인 단계 유지
- React UI는 유지하고 web component wrapper만 추가
- `global contract + element attribute override` 둘 다 지원
- 기본 스타일 격리는 Shadow DOM
- onboarding agent는 widget 생성자가 아니라 attach installer 역할로 축소

