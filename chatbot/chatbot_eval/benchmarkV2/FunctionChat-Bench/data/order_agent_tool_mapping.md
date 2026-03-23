# 주문 서브에이전트 및 도구 매핑 가이드

이 문서는 챗봇의 주문 관련 시나리오별로 호출되는 에이전트 노드와 실제 도구(Tool)를 정의합니다.  
`chatbot/src/graph/nodes/order_flow.py`의 최신 로직과 완전히 동기화되어 있습니다.

---

## 1. 전체 워크플로우 (정상 운영 vs 평가 모드)

```
[운영 모드 흐름]
START → guardrail → planner → supervisor → order_entry → order_intent_router → {서브에이전트} → final_generator

[평가 직행 모드 (is_direct_routing=True)]
START → order_intent_router → {서브에이전트} → final_generator
```

> 평가 직행 모드는 `is_direct_routing` 플래그를 통해 활성화되며,  
> `guardrail`, `planner`, `supervisor`, `order_entry` 노드를 완전히 건너뜁니다.

---

## 2. 의도 분류 우선순위 (`_classify_order_action`)

`order_intent_router`가 사용자 질문을 받아 아래 우선순위 순서대로 의도를 판별합니다.

| 순위 | 분류 카테고리 | 조건 | 결과 |
| :--- | :--- | :--- | :--- |
| **절대 0순위** | **데이터 결핍 / 명시적 목록 요청** | 주문번호(ORD-)가 없고, "번호몰라", "리스트업", "주문목록", "주문내역", "최근주문" 등이 있을 때 | `list_orders` |
| **0순위** | **명시적 최종 의사 / 번복 표현** | "환불말고취소", "그냥취소", "취소할게", "취소해주세요" 등 확정 의사 표현 | 해당 액션 |
| **2순위** | **명확한 액션 키워드** | "취소", "환불/반품", "배송조회/송장", "교환" 등 직접적 지시어 | 해당 액션 |
| **3순위** | **사유 기반 추론** | "실수로 주문", "파손됨", "사이즈 안맞아", "택배 안와" 등 상황 설명 | 유추한 액션 |
| **4순위** | **이전 액션 유지** | 이전 대화에서 결정된 액션이 있으면 그대로 유지 | 기존 액션 |
| **기본값** | **보수적 기본값** | 어떤 의도도 파악 불가 | `list_orders` |

---

## 3. 서브에이전트별 시나리오 및 분기

### 3-1. `order_list_subagent` (주문내역 조회)
**호출 도구**: `get_user_orders`

| 진입 조건 | 예시 발화 |
| :--- | :--- |
| 주문번호 없이 "번호를 모른다" 언급 | "취소하고 싶은데 번호를 몰라요" |
| "리스트업", "주문목록", "주문내역" 등 | "지금까지 주문한 거 리스트업해줘" |
| "최근 주문한 내역 보여줘" | "최근 구매 내역 좀 보여주세요" |
| "내가 뭐 샀는지 모르겠어" | "뭐샀어요?" |

**동작**: 최근 30일 주문 목록을 최대 10건 조회 후 UI에 목록으로 표출합니다.

---

### 3-2. `cancel_subagent` (주문 취소)
**호출 도구**: `cancel` (내부: `cancel_order_via_adapter`)

| 진입 조건 | 예시 발화 |
| :--- | :--- |
| "취소", "결제취소", "철회" 등 명시적 취소 | "ORD-001 취소해주세요" |
| "다시 주문하려고", "실수로 주문", "잘못 눌렀어" | "방금 결제한 주문 취소해주세요. 실수했어요" |
| 번복 표현 "환불말고 취소" | "아니 그냥 취소할게요" |

**분기 구조**:
```
cancel_subagent 실행
→ order_id가 없는 경우: get_user_orders 호출 → UI: show_order_list
→ order_id가 있는 경우: cancel_order_via_adapter 호출
  → confirmed=None: confirm_order_action UI 표출 (HITL 확인 요청)
  → confirmed=True: 즉시 취소 처리 (status: "cancelled") → completed
  → 취소 불가 상태(배송 완료 등): error 반환 → failed
```

---

### 3-3. `refund_subagent` (환불/반품)
**호출 도구**: `refund` (내부: `register_return_via_adapter`)

| 진입 조건 | 예시 발화 |
| :--- | :--- |
| "환불", "반품", "반송", "환급" | "ORD-002 반품하고 환불받고 싶어요" |
| 불량/파손 사유 추론 | "상품이 파손되어서 환불 신청하려고요" |
| "설명과 달라", "사진과 달라", "오배송" | "배송받은 상품이 화면과 완전히 달라요" |

**분기 구조**:
```
refund_subagent 실행
→ order_id 없음: get_user_orders → UI: show_order_list
→ order_id 있음: register_return_via_adapter 호출
  → confirmed=None: confirm_order_action UI 표출 (HITL 확인 요청)
  → confirmed=True: 반품 접수 처리 (status: "refund_requested") → completed
  → 기간 초과/불가: error → failed
```

---

### 3-4. `shipping_subagent` (배송 조회)
**호출 도구**: `shipping` (내부: `get_shipping_via_adapter`)

| 진입 조건 | 예시 발화 |
| :--- | :--- |
| "배송조회", "배송상태", "송장번호" | "ORD-001 지금 어디쯤인가요?" |
| "택배 언제와", "도착 예정", "현재위치" | "언제 도착해요?" |
| "배송 + 조회/상태/위치" 조합 | "배송 상태 확인하고 싶어요" |

**동작 및 특징**:
- **즉시 호출 (No HITL)**: 취소/환불 등과 달리 정보 조회 기능이므로 "정말 조회할까요?"라는 **최종 확인 단계 없이** 주문번호가 식별되면 즉시 시스템을 호출합니다.
- **예외 처리**: "배송받은 상품이 파손"처럼 이미 완료된 맥락은 `refund`로 자동 유추됩니다.

**분기 구조**:
```
shipping_subagent 실행
→ order_id 없음: get_user_orders → UI: show_order_list
→ order_id 있음: get_shipping_via_adapter 즉시 호출
  → 조회 성공: 배송상태/택배사/송장번호 반환 → completed
  → 등록되지 않은 주문: error → failed
```

---

### 3-5. `exchange_subagent` (교환/옵션변경)
**호출 도구**: `exchange` 또는 `change_option` (세부 판별)

| 진입 조건 | 예시 발화 |
| :--- | :--- |
| "교환", "교환접수", "맞교환" | "ORD-003 교환하고 싶어요" |
| "사이즈 변경", "색상 바꿔줘" | "사이즈가 너무 커서 다른 사이즈로 교환하고 싶습니다" |
| "옵션 잘못 선택했어" | "방금 결제했는데 옵션 좀 바꿔주세요" |

**시나리오 및 분기 기준**:

| 구분 | **옵션변경 (change_option)** | **교환 (exchange)** |
| :--- | :--- | :--- |
| **핵심 시나리오** | **배송 전(PAID/PREPARING)** 상태에서 단순 옵션을 바꿈 | **배송 후(DELIVERED)** 제품을 받은 후 새 제품으로 교체함 |
| **대상 주문 상태** | 결제완료, 상품준비중 | 배송완료 |
| **사용자 인터랙션** | 변경 가능한 옵션 목록 선택 (`new_option`) | 교환 실행 여부 최종 확인 (`confirmation`) |

**도구별 세부 동작 상세**:

- **[시나리오 A] 배송 전 옵션 변경 (`change_option`)**
  1. 현재 주문 내 상품에 대해 변경 가능한 다른 옵션(색상, 사이즈 등)이 있는지 확인합니다.
  2. 조회된 옵션 데이터를 바탕으로 사용자에게 선택 UI(`show_option_list`)를 제공합니다.
  3. 사용자가 새 옵션을 선택하면 실제 DB의 주문 정보를 즉시 업데이트합니다.

- **[시나리오 B] 배송 후 일반 교환 (`exchange`)**
  1. 기존 물품의 회수(반품)와 새 물품의 발송(재배송) 절차를 수반합니다.
  2. 시스템은 교환 접수 전, 사용자에게 최종 의사를 묻는 확인 UI(`confirm_order_action`)를 띄웁니다.
  3. 사용자가 승인(`confirmed=True`)하면 상태를 업데이트하고 교환 프로세스를 시작합니다.

**분기 구조**:
```
exchange_subagent 실행
→ order_id 없음: get_user_orders → UI: show_order_list
→ order_id 있음:
  → change_option 경로: needs_new_option 여부 확인
    → 옵션 목록 없음: show_option_list UI 표출 (awaiting_resume_for="new_option")
    → 옵션 선택됨: 옵션 변경 처리 → completed
  → exchange 경로:
    → confirmed=None: confirm_order_action UI (HITL)
    → confirmed=True: 교환 접수 (status: "processing (exchange)") → completed
```

---

## 4. 액션 상태(action_status) 전이

```
ready  →  [도구 호출]  →  waiting_user  →  [사용자 응답]  →  completed
                      ↓                                       ↑
                    failed                              (재진입 후 루프)
```

| 상태 | 설명 | 다음 노드 |
| :--- | :--- | :--- |
| `ready` | 서브에이전트 실행 직전 초기 상태 | 해당 서브에이전트 |
| `waiting_user` | UI 입력 또는 사용자 확인 대기 중 | `final_generator` |
| `completed` | 작업 성공적으로 완료 | `supervisor` |
| `failed` | 오류 발생 (처리 불가 상태 등) | `final_generator` |

---

## 5. UI 액션별 대기 상태

서브에이전트 실행 결과에 따라 아래 UI 액션이 발동되며, 챗봇은 이 상태에서 사용자 입력을 기다립니다.

| UI 액션 | awaiting_resume_for | 설명 |
| :--- | :--- | :--- |
| `show_order_list` | `order_selection` | 주문 목록 표출 후 사용자가 특정 주문을 선택하도록 대기 |
| `show_option_list` | `new_option` | 옵션 목록 표출 후 사용자가 새 옵션을 선택하도록 대기 |
| `confirm_order_action` | `confirmation` | 작업 실행 전 최종 확인 요청 ("정말로 취소하시겠습니까?") |
| `show_address_search` | `address` | 반품 수거지 주소 입력 UI 표출 |

---

## 6. 실행 정책: 주문번호 기반 즉시 처리 및 안전 정책(HITL)

### 1) 주문번호(`order_id`) 기반 즉시 진입
- **동작**: 사용자의 첫 질문에 이미 `ORD-` 등의 주문번호가 포함되어 있다면, "주문번호를 알려주세요"라는 추가 질문 단계를 **완전히 생략**합니다.
- **효과**: `order_intent_router`가 번호를 감지하는 즉시 해당 업무의 담당 서브에이전트로 상태를 넘겨 프로세스 시간을 대폭 단축합니다.

### 2) 사용자 확인 원칙 (Human-In-The-Loop)
- **메커니즘**: 모든 유료 거래/취소 관련 도구(`cancel`, `refund`, `exchange`)는 **`confirmed`** 파라미터를 가집니다.
- **승인 절차**:
    - 주문번호를 인지했더라도, 실제 DB 반영 전에는 반드시 사용자에게 최종 확인을 구합니다.
    - 사용자가 "응", "진행해줘"라고 답할 때까지 실제 처리는 **Interrupt(중단)** 상태로 대기합니다.
- **예외 (즉시 실행)**: 사용자가 처음부터 "확실하니까 그냥 바로 취소해줘"라고 **명시적으로 승인 의사**를 밝힌 경우에는 확인 단계 없이 즉시 처리가 가능합니다.

---

*최종 업데이트: 2026-03-18 (order_flow.py 전체 로직 완전 동기화)*
