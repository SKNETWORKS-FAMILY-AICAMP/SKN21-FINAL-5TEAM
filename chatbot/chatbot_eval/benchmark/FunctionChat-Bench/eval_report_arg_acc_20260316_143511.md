# 🤖 챗봇 성능 평가 보고서 (Argument Accuracy)
- **생성 일시**: 2026-03-16 14:35:11
- **평가 프레임워크**: FunctionChat-Bench
- **대상 모델**: inhouse
- **LangSmith 트레이스 수**: 1개
- **실행 결과**: 1/1 벤치마크 성공
 
## 📖 평가 벤치마크 설명
본 평가는 **FunctionChat-Bench** 프레임워크를 기반으로 수행되었습니다.
 
### 1. Argument Accuracy (Dialog)
- **평가 목적**: 챗봇이 멀티턴 대화에서 필요한 인자(Argument)를 얼마나 정확하게 추출하고 올바른 Tool을 호출하는지 측정합니다.
- **핵심 지표**: 필수 인자 추출 정확도, Tool 선택 정확성, enum 값 범위 준수 여부를 검증합니다.
- **데이터셋**: `C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\chatbot\chatbot_eval\benchmark\FunctionChat-Bench\data\my_eval_arg_accuracy_dialogs.jsonl` (총 27개 전체 평가)

## 📊 Argument Accuracy (Dialog) 요약
| 지표 | 결과 |
| :--- | :--- |
| **전체 테스트 케이스** | 27개 |
| **통과 수 (Pass)** | 6개 |
| **Call 정답률** | 22.2% |
| **Micro 평균** | 22.2% |

## 📝 상세 실행 로그 (Tool Calls)
| 번호 | 결과 | 질의 | 호출된 도구 (Tool Name) | 인자 (Arguments) |
| :--- | :--- | :--- | :--- | :--- |
| 1 | ✅ PASS | 주문번호 ORD-eval_dataset-0001 배송이 너무 느려서 취소하려고 합니다. 처리해주세요. | `cancel` | `{"order_id": "ORD-eval_dataset-0001", "user_id": 1}` |
| 2 | ❌ FAIL | 받은 ORD-eval_dataset-0002 상품이 완전히 파손되어 있어서 환불 신청합니다. 판매자 책임입니다. | `refund` | `{"order_id": "ORD-eval_dataset-0002", "user_id": 1}` |
| 3 | ✅ PASS | ORD-eval_dataset-0003 주문건, 사이즈가 너무 커서 교환할게요. | `exchange` | `{"order_id": "ORD-eval_dataset-0003", "user_id": 1}` |
| 4 | ✅ PASS | 방금 주문한 내역의 배송 상태를 알고 싶은데 주문번호는 까먹었어요. | `shipping` | `{"user_id": 1}` |
| 5 | ✅ PASS | ORD-eval_dataset-0001 주문 도대체 언제 도착하는지 배송 조회 좀 해주세요. | `shipping` | `{"order_id": "ORD-eval_dataset-0001", "user_id": 1}` |
| 6 | ❌ FAIL | 여름에 입기 좋은 시원한 반팔 티셔츠 찾아줘. | `search_by_text_clip` | `{"query": "\uc5ec\ub984\uc5d0 \uc785\uae30 \uc88b\uc740 \uc2dc\uc6d0\ud55c \ubc18\ud314 \ud2f0\uc154\uce20 ."}` |
| 7 | ❌ FAIL | 결혼식 하객으로 입고 갈만한 깔끔한 정장 세트 추천해줄래? | `recommend_clothes` | `{"category": "Formal", "user_id": 1}` |
| 8 | ✅ PASS | 제가 입던 원피스를 중고로 팔려고 하는데 폼 좀 열어주세요. | `open_used_sale_form` | `{}` |
| 9 | ❌ FAIL | 주문한 ORD-eval_dataset-0001 상품 너무 마음에 들어요! 별점 5점 줄게요. | - | - |
| 10 | ❌ FAIL | 저기요, ORD-eval_dataset-0004 주문건 아직도 상품준비중이던데 그냥 취소할래요. 배송 지연되어서요. | `cancel` | `{"order_id": "ORD-eval_dataset-0004", "user_id": 1}` |
| 11 | ❌ FAIL | 이거 ORD-eval_dataset-0005 배송받아서 까봤는데 불량품이네요;; 환불해주세요. | `refund` | `{"order_id": "ORD-eval_dataset-0005", "user_id": 1}` |
| 12 | ❌ FAIL | 옷이 저한테 안 맞네요 ㅠㅠ ORD-eval_dataset-0006 사이즈 불일치로 교환하고 싶습니다. | `exchange` | `{"order_id": "ORD-eval_dataset-0006", "user_id": 1}` |
| 13 | ❌ FAIL | 저 주문내역 확인좀요. 결제는 했는데 주문번호를 안적어놨네요. | `refund` | `{"user_id": 1}` |
| 14 | ❌ FAIL | 주문번호 ORD-eval_dataset-0004 배송 언제 시작하나요? 조회 부탁합니다. | `shipping` | `{"order_id": "ORD-eval_dataset-0004", "user_id": 1}` |
| 15 | ❌ FAIL | 요즘 유행하는 와이드 팬츠 검색 좀 해줄래요? | `search_by_text_clip` | `{"query": "\uc694\uc998 \uc720\ud589\ud558\ub294 \uc640\uc774\ub4dc \ud32c\uce20 \uac80\uc0c9 \uc880 \ud574\uc904\ub798\uc694?"}` |
| 16 | ❌ FAIL | 이번 주말에 데이트가 있는데 입을만한 예쁜 원피스 추천 좀요. | `recommend_clothes` | `{"category": "Dress", "user_id": 1}` |
| 17 | ❌ FAIL | 안 입는 패딩 중고 판매 등록하고 싶어요. 어떻게 하나요? | `search_knowledge_base` | `{"query": "\uc548 \uc785\ub294 \ud328\ub529 \uc911\uace0 \ud310\ub9e4 \ub4f1\ub85d\ud558\uace0 \uc2f6\uc5b4\uc694. \uc5b4\ub5bb\uac8c \ud558\ub098\uc694?"}` |
| 18 | ❌ FAIL | ORD-eval_dataset-0004 받아보니 가성비 대박이네요 ㅋㅋㅋ 리뷰 5점으로 남겨주세요. | `create_review` | `{"rating": 5, "order_id": "ORD-eval_dataset-0004", "user_id": 1}` |
| 19 | ❌ FAIL | 수고하십니다. ORD-eval_dataset-0007 결제한거 취소 부탁드립니다. 딴데서 샀어요. 배송이 늦어져서요. | `cancel` | `{"order_id": "ORD-eval_dataset-0007", "user_id": 1}` |
| 20 | ❌ FAIL | 상품 상태가 영 아니네요. 찢어져서 왔습니다. ORD-eval_dataset-0008 환불 처리 부탁드려요. | `refund` | `{"order_id": "ORD-eval_dataset-0008", "user_id": 1}` |
| 21 | ❌ FAIL | ORD-eval_dataset-0009 교환 신청합니다. 생각보다 너무 작게 나왔네요. | `exchange` | `{"order_id": "ORD-eval_dataset-0009", "user_id": 1}` |
| 22 | ❌ FAIL | 배송조회 하고싶은데 주문번호 없이도 되나요? 언제 오는지 알고싶어요. | `shipping` | `{"user_id": 1}` |
| 23 | ❌ FAIL | ORD-eval_dataset-0007 이거 택배 어디쯤 왔는지 궁금해요. | `shipping` | `{"order_id": "ORD-eval_dataset-0007", "user_id": 1}` |
| 24 | ❌ FAIL | 캐주얼하게 입기 편한 오버핏 맨투맨 있나요? | - | - |
| 25 | ❌ FAIL | 운동할 때 입기 좋은 기능성 트레이닝복 상하의 찾아줘. | `search_by_text_clip` | `{"query": "\uc6b4\ub3d9\ud560 \ub54c \uc785\uae30 \uc88b\uc740 \uae30\ub2a5\uc131 \ud2b8\ub808\uc774\ub2dd\ubcf5 \uc0c1\ud558\uc758 ."}` |
| 26 | ✅ PASS | 사이즈 미스난 신발 당근처럼 중고판매 가능하죠? 신청서 띄워주세요. | `open_used_sale_form` | `{}` |
| 27 | ❌ FAIL | 배송도 빠르고 재질도 좋네요~ ORD-eval_dataset-0007 건에 대해 5점 리뷰 작성할게요. | `create_review` | `{"rating": 5, "order_id": "ORD-eval_dataset-0007", "user_id": 1}` |

---
*본 보고서는 `run_evaluate.py`에 의해 자동으로 생성되었습니다.*
