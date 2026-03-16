# 🛠️ 상황별 도구 가이드 (Tool Usage Guide)

이 문서는 챗봇이 각 상황(시나리오)에서 어떤 도구(Tool)를 사용해야 하며, 어떤 인자(Arguments)가 필수적으로 필요한지 정리한 가이드입니다.

---

## 1. 주문 관련 시나리오 (Order Management)

| 상황 | 도구명 (Tool) | 필수 인자 (Required) | 수집 및 처리 지침 |
| :--- | :--- | :--- | :--- |
| **배송 조회** | `shipping` | `order_id` | 사용자가 주문 상태나 위치를 물어볼 때 사용합니다. |
| **주문 취소** | `cancel` | `order_id`, `reason` | **배송 전**에만 가능합니다. 취소 사유가 누락되지 않도록 주의하세요. |
| **환불 신청** | `refund` | `order_id`, `reason` | **배송 중/완료** 상태에서 사용합니다. 판매자 귀책(`is_seller_fault`) 여부를 판단하면 좋습니다. |
| **교환 신청** | `exchange` | `order_id`, `reason` | **배송 중/완료** 상태에서 사용합니다. 가능하면 새로운 옵션(`new_option_id`)을 물어보세요. |
| **옵션 변경** | `change_option` | `order_id`, `new_option_id` | **배송 전**에 한해 상품의 사이즈나 색상을 바꿀 때 사용합니다. |
| **주문 목록 조회** | `get_user_orders` | `user_id` | 사용자가 주문번호를 모르거나, 선택이 필요할 때 목록 UI를 띄워줍니다. |

---

## 2. 상품 검색 및 추천 (Search & Recommendation)

| 상황 | 도구명 (Tool) | 필수 인자 (Required) | 수집 및 처리 지침 |
| :--- | :--- | :--- | :--- |
| **옷 추천** | `recommend_clothes` | `category` | `Topwear`, `Dress` 등 영어 카테고리명으로 변환하여 호출합니다. |
| **텍스트 검색** | `search_by_text_clip` | `query` | 무드나 스타일(예: "시원한 여름 옷") 기반 검색에 활용합니다. |
| **이미지 검색** | `search_by_image` | `image_bytes` | 사용자가 이미지를 업로드했을 때 유사 상품을 찾습니다. |

---

## 3. 고객 지원 및 정보 제공 (Knowledge)

| 상황 | 도구명 (Tool) | 필수 인자 (Required) | 수집 및 처리 지침 |
| :--- | :--- | :--- | :--- |
| **규정/정책 문의** | `search_knowledge_base` | `query` | 배송비, 반품 규정 등 '쇼핑몰 정보'에 대한 질문 시 사용합니다. |

---

## 4. 리뷰 및 중고 거래 (Engagement)

| 상황 | 도구명 (Tool) | 필수 인자 (Required) | 수집 및 처리 지침 |
| :--- | :--- | :--- | :--- |
| **리뷰 작성** | `create_review` | `order_id` | 평점(`rating`)과 내용(`content`)을 함께 보내면 더 좋습니다. |
| **리뷰 초안 생성** | `generate_review_draft` | `product_name`, `satisfaction` | 사용자가 쓸 내용을 고민할 때 AI가 초안 3가지를 제안합니다. |
| **중고 판매 폼** | `open_used_sale_form` | - | 텍스트 대신 UI 폼을 즉시 띄우고 싶을 때 사용합니다. |
| **중고 등록** | `register_used_sale` | `category_id`, `item_name`, `description`, `condition_id` | 사용자가 내용을 직접 말했을 때 API에 바로 등록합니다. |
| **수거 신청** | `request_pickup` | `sale_id`, `pickup_date`, `pickup_address` | 중고 물품 수거 일정을 잡을 때 사용합니다. |

---

## 5. 기타 (System)

| 상황 | 도구명 (Tool) | 필수 인자 (Required) | 수집 및 처리 지침 |
| :--- | :--- | :--- | :--- |
| **상품권 등록** | `register_gift_card` | `code` | 쿠폰이나 기프트카드 번호를 입력받아 충전할 때 사용합니다. |

---

### 💡 공통 지침
- **`user_id`**: 모든 도구에서 `user_id`는 기본적으로 `1`을 사용하거나 벤치마크 지침에 따릅니다.
- **Action-Oriented**: 필요한 정보(`order_id`, `reason` 등)가 발화에 포함되어 있다면 묻지 말고 즉시 도구를 호출하세요.
- **Zero-step**: 불필요한 배송 조회(`shipping`) 단계를 거치지 말고, 바로 최종 액션(`cancel`, `refund` 등)을 수행하세요.
