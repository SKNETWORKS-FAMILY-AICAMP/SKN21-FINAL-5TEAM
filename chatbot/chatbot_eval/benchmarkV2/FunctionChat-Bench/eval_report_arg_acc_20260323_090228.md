# 🤖 챗봇 성능 평가 보고서 (Argument Accuracy)
- **생성 일시**: 2026-03-23 09:02:28
- **평가 프레임워크**: FunctionChat-Bench
- **대상 모델**: gpt-4o-mini
- **LangSmith 트레이스 수**: 0개
- **가드레일 활성화**: ✅ ON
- **소요 시간**: 37.54초
- **실행 결과**: 1/1 벤치마크 성공
 
## 📖 평가 벤치마크 설명
본 평가는 **FunctionChat-Bench** 프레임워크를 기반으로 수행되었습니다.
 
### 1. Argument Accuracy (Dialog)
- **평가 목적**: 챗봇이 멀티턴 대화에서 필요한 인자(Argument)를 얼마나 정확하게 추출하고 올바른 Tool을 호출하는지 측정합니다.
- **핵심 지표**: 필수 인자 추출 정확도, Tool 선택 정확성, enum 값 범위 준수 여부를 검증합니다.
- **데이터셋**: `C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\chatbot\chatbot_eval\benchmarkV2\FunctionChat-Bench\data\50\data\my_eval_arg_accuracy_dialogs50.jsonl` (총 50개 전체 평가)

## 📊 Argument Accuracy (Dialog) 요약
| 지표 | 결과 |
| :--- | :--- |
| **전체 테스트 케이스** | 50개 |
| **통과 수 (Pass)** | 50개 |
| **Call 정답률** | 100.0% |
| **Micro 평균** | 100.0% |

## 📝 상세 실행 로그 (Tool Calls)
| 번호 | 결과 | 질의 | 기대되는 도구 (Expected) | 호출된 도구 (Model) | 분류 로직 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | ✅ PASS | 뭐가 맞는지 혼란스러우니 우선 내가 최근에 한 주문 기록부터 확인하게 해줘. | `get_user_orders` | `get_user_orders` | `LLM` |
| 2 | ✅ PASS | 최근 주문만 먼저 보여줘. | `get_user_orders` | `get_user_orders` | `LLM` |
| 3 | ✅ PASS | 뭘로 처리해야 할지 너무 헷갈립니다—취소인지 환불인지 아직 결정을 못 했어요. 그래서 제가 최근에 한 주문들 목록부터 확인하고 싶어요, 보여주세요. | `get_user_orders` | `get_user_orders` | `LLM` |
| 4 | ✅ PASS | 사이즈 때문에 바꾸려다 말았어. 아니, 지금 바꾸는 건 아니고 최근에 내가 주문한 것들만 먼저 보여줘. | `get_user_orders` | `get_user_orders` | `LLM` |
| 5 | ✅ PASS | 주문번호를 잊어버렸는데, 가장 최근에 결제한 주문 목록을 먼저 보여주실래요? | `get_user_orders` | `get_user_orders` | `LLM` |
| 6 | ✅ PASS | 결론부터 말해서, 내 최근 주문 히스토리부터 보여줘. | `get_user_orders` | `get_user_orders` | `LLM` |
| 7 | ✅ PASS | 처음엔 취소하려다가 이미 받아서 못 했고요. 결정을 위해 최근 주문내역만 먼저 볼 수 있게 목록 좀 보여주세요. | `get_user_orders` | `get_user_orders` | `LLM` |
| 8 | ✅ PASS | 아, 취소하려다 말았는데… 아니, 환불일 수도 있겠네요. 아무튼 내 최근 주문들부터 보여줘요. | `get_user_orders` | `get_user_orders` | `LLM` |
| 9 | ✅ PASS | 주문번호를 잊어버려서요, 제 최근 주문 목록 좀 볼 수 있을까요? | `get_user_orders` | `get_user_orders` | `LLM` |
| 10 | ✅ PASS | 주문번호를 까먹어서 확인이 필요해요. 교환이든 옵션 변경이든 결정은 나중에 하고, 최근 주문 내역부터 보여주세요. | `get_user_orders` | `get_user_orders` | `LLM` |
| 11 | ✅ PASS | 주문번호 기억이 안 나요. 최근 주문내역부터 바로 보여줘요. | `get_user_orders` | `get_user_orders` | `LLM` |
| 12 | ✅ PASS | 최근 주문 목록부터 보여줘요, 주문번호가 기억이 안 나거든요. | `get_user_orders` | `get_user_orders` | `LLM` |
| 13 | ✅ PASS | 주문번호를 까먹어서, 환불이나 교환은 잠깐 미루고 최근 주문 내역부터 보여줄래? | `get_user_orders` | `get_user_orders` | `LLM` |
| 14 | ✅ PASS | 최근에 결제한 주문들만 쭉 보여줘. | `get_user_orders` | `get_user_orders` | `LLM` |
| 15 | ✅ PASS | 생각이 바뀌어서요, ORD-eval_dataset-0001은 반품 말고 주문 자체를 취소하고 싶어요. | `cancel` | `cancel` | `LLM` |
| 16 | ✅ PASS | ORD-eval_dataset-0001 그냥 주문 취소로 해줘요. | `cancel` | `cancel` | `LLM` |
| 17 | ✅ PASS | 처리 단계가 아직 초기라면 좋겠는데, ORD-eval_dataset-0001은 환불 절차 대신 주문 취소로 부탁드립니다. | `cancel` | `cancel` | `LLM` |
| 18 | ✅ PASS | 처음엔 옵션 바꿔볼까 했지만 마음 바꿨어요, ORD-eval_dataset-0007 최종 취소로 해 주세요. | `cancel` | `cancel` | `LLM` |
| 19 | ✅ PASS | 교환이나 옵션 변경, 환불도 생각해봤지만 결국 ORD-eval_dataset-0004는 취소로 확정해주세요. | `cancel` | `cancel` | `LLM` |
| 20 | ✅ PASS | 사이즈를 잘못 골라서요, ORD-eval_dataset-0004는 교환이나 옵션 변경 고민 끝에 주문 취소로 부탁드립니다. | `cancel` | `cancel` | `LLM` |
| 21 | ✅ PASS | 환불이나 교환 하려다 말았고, 지금 준비 중이면 더 좋고요; 어쨌든 ORD-eval_dataset-0004 취소해주세요. | `cancel` | `cancel` | `LLM` |
| 22 | ✅ PASS | 처음엔 환불하려 했지만 번복합니다, ORD-eval_dataset-0001은 취소로만 진행해 주세요. | `cancel` | `cancel` | `LLM` |
| 23 | ✅ PASS | 옵션 바꾸려다 헷갈려서 포기했어요. ORD-eval_dataset-0004 주문은 취소로 진행해주세요. | `cancel` | `cancel` | `LLM` |
| 24 | ✅ PASS | 이거 그냥 취소해줘요. | `cancel` | `cancel` | `LLM` |
| 25 | ✅ PASS | ORD-eval_dataset-0003 원래 취소하려 했지만 이미 받았고, 최종적으로 환불 요청합니다. | `refund` | `refund` | `LLM` |
| 26 | ✅ PASS | ORD-eval_dataset-0003 환불 부탁드립니다. | `refund` | `refund` | `LLM` |
| 27 | ✅ PASS | 처음엔 교환할까 했는데요, ORD-eval_dataset-0006은 최종으로 환불만 부탁해요. | `refund` | `refund` | `LLM` |
| 28 | ✅ PASS | 사이즈가 맞지 않아 착용이 어려우니, ORD-eval_dataset-0003은 교환 대신 환불로 진행해 주세요. | `refund` | `refund` | `LLM` |
| 29 | ✅ PASS | ORD-eval_dataset-0009 환불해주세요, 파손입니다. | `refund` | `refund` | `LLM` |
| 30 | ✅ PASS | 사이즈도 안 맞고 표면에 흠집까지 있어서, ORD-eval_dataset-0006은 회수 후 환불 처리해주세요. | `refund` | `refund` | `LLM` |
| 31 | ✅ PASS | ORD-eval_dataset-0006 그냥 환불로 해줘요. | `refund` | `refund` | `LLM` |
| 32 | ✅ PASS | ORD-eval_dataset-0006 받아보니 상태가 마음에 안 들어요, 교환도 취소도 아니고 수거해서 금액만 환불해주시면 됩니다. | `refund` | `refund` | `LLM` |
| 33 | ✅ PASS | 처음엔 교환하려 했지만, ORD-eval_dataset-0009는 최종 환불로 해주세요. | `refund` | `refund` | `LLM` |
| 34 | ✅ PASS | 처음엔 교환하려 했는데 아니에요, ORD-eval_dataset-0005는 결국 환불로 할게요. | `refund` | `refund` | `LLM` |
| 35 | ✅ PASS | 주문 ORD-eval_dataset-0002는 이미 받아봤고, 취소나 환불 말고 동일 상품으로 교환 처리해주세요. | `exchange` | `exchange` | `LLM` |
| 36 | ✅ PASS | 사이즈가 맞지 않아 주문 ORD-eval_dataset-0002는 동일 제품으로 교환 부탁드립니다. | `exchange` | `exchange` | `LLM` |
| 37 | ✅ PASS | 사이즈가 너무 커서요, ORD-eval_dataset-0005 동일 상품으로 한 치수 작은 걸로 교환해주세요. | `exchange` | `exchange` | `LLM` |
| 38 | ✅ PASS | 옵션 바꾸려다 말았고요, 주문 ORD-eval_dataset-0002는 최종으로 같은 상품으로 교환할게요, 취소나 환불은 아닙니다. | `exchange` | `exchange` | `LLM` |
| 39 | ✅ PASS | ORD-eval_dataset-0005 처음엔 환불 생각했지만, 아니요 결국 같은 거 더 작은 사이즈로 교환할게요. | `exchange` | `exchange` | `LLM` |
| 40 | ✅ PASS | ORD-eval_dataset-0002 같은 걸로 교환해줘요. | `exchange` | `exchange` | `LLM` |
| 41 | ✅ PASS | 이미 수령했고 제품은 마음에 들지만 색상만 바꾸고 싶어서요, 주문 ORD-eval_dataset-0002는 환불·취소 대신 동일 모델로 교환 처리 부탁드려요. | `exchange` | `exchange` | `LLM` |
| 42 | ✅ PASS | ORD-eval_dataset-0005 사이즈가 커서 동일 제품 작은 사이즈로 교환 부탁드려요, 취소나 환불은 아니에요. | `exchange` | `exchange` | `LLM` |
| 43 | ✅ PASS | 생각 바뀌었어요—교환 아니라 ORD-eval_dataset-0001은 옵션만 바꿀게요, 이걸로 최종이에요. | `change_option` | `change_option` | `LLM` |
| 44 | ✅ PASS | ORD-eval_dataset-0004 옵션(사이즈)만 바꿔주세요. 취소나 환불은 원치 않습니다. | `change_option` | `change_option` | `LLM` |
| 45 | ✅ PASS | 사이즈가 걱정돼서요, ORD-eval_dataset-0004는 교환 말고 옵션 변경만 부탁드립니다. | `change_option` | `change_option` | `LLM` |
| 46 | ✅ PASS | 교환 대신 옵션만 바꾸고 싶습니다. 주문번호는 ORD-eval_dataset-0001이며, 취소나 환불은 원하지 않습니다. | `change_option` | `change_option` | `LLM` |
| 47 | ✅ PASS | 사이즈가 애매해서요, ORD-eval_dataset-0007은 옵션 변경만 진행해 주세요. | `change_option` | `change_option` | `LLM` |
| 48 | ✅ PASS | 지금 준비 중이면 ORD-eval_dataset-0004 사이즈 선택만 다른 걸로 변경해 주세요. 환불이나 취소는 안 하겠습니다. | `change_option` | `change_option` | `LLM` |
| 49 | ✅ PASS | 처음엔 교환하려 했지만 생각 바꿨어요. ORD-eval_dataset-0004는 최종으로 옵션 변경만 원합니다. | `change_option` | `change_option` | `LLM` |
| 50 | ✅ PASS | ORD-eval_dataset-0004 옵션만 바꿀 수 있을까요? | `change_option` | `change_option` | `LLM` |

## 💬 수신된 사용자 쿼리 목록
| 번호 | 사용자 질의 (Query) |
| :--- | :--- |
| 1 | 뭐가 맞는지 혼란스러우니 우선 내가 최근에 한 주문 기록부터 확인하게 해줘. |
| 2 | 최근 주문만 먼저 보여줘. |
| 3 | 뭘로 처리해야 할지 너무 헷갈립니다—취소인지 환불인지 아직 결정을 못 했어요. 그래서 제가 최근에 한 주문들 목록부터 확인하고 싶어요, 보여주세요. |
| 4 | 사이즈 때문에 바꾸려다 말았어. 아니, 지금 바꾸는 건 아니고 최근에 내가 주문한 것들만 먼저 보여줘. |
| 5 | 주문번호를 잊어버렸는데, 가장 최근에 결제한 주문 목록을 먼저 보여주실래요? |
| 6 | 결론부터 말해서, 내 최근 주문 히스토리부터 보여줘. |
| 7 | 처음엔 취소하려다가 이미 받아서 못 했고요. 결정을 위해 최근 주문내역만 먼저 볼 수 있게 목록 좀 보여주세요. |
| 8 | 아, 취소하려다 말았는데… 아니, 환불일 수도 있겠네요. 아무튼 내 최근 주문들부터 보여줘요. |
| 9 | 주문번호를 잊어버려서요, 제 최근 주문 목록 좀 볼 수 있을까요? |
| 10 | 주문번호를 까먹어서 확인이 필요해요. 교환이든 옵션 변경이든 결정은 나중에 하고, 최근 주문 내역부터 보여주세요. |
| 11 | 주문번호 기억이 안 나요. 최근 주문내역부터 바로 보여줘요. |
| 12 | 최근 주문 목록부터 보여줘요, 주문번호가 기억이 안 나거든요. |
| 13 | 주문번호를 까먹어서, 환불이나 교환은 잠깐 미루고 최근 주문 내역부터 보여줄래? |
| 14 | 최근에 결제한 주문들만 쭉 보여줘. |
| 15 | 생각이 바뀌어서요, ORD-eval_dataset-0001은 반품 말고 주문 자체를 취소하고 싶어요. |
| 16 | ORD-eval_dataset-0001 그냥 주문 취소로 해줘요. |
| 17 | 처리 단계가 아직 초기라면 좋겠는데, ORD-eval_dataset-0001은 환불 절차 대신 주문 취소로 부탁드립니다. |
| 18 | 처음엔 옵션 바꿔볼까 했지만 마음 바꿨어요, ORD-eval_dataset-0007 최종 취소로 해 주세요. |
| 19 | 교환이나 옵션 변경, 환불도 생각해봤지만 결국 ORD-eval_dataset-0004는 취소로 확정해주세요. |
| 20 | 사이즈를 잘못 골라서요, ORD-eval_dataset-0004는 교환이나 옵션 변경 고민 끝에 주문 취소로 부탁드립니다. |
| 21 | 환불이나 교환 하려다 말았고, 지금 준비 중이면 더 좋고요; 어쨌든 ORD-eval_dataset-0004 취소해주세요. |
| 22 | 처음엔 환불하려 했지만 번복합니다, ORD-eval_dataset-0001은 취소로만 진행해 주세요. |
| 23 | 옵션 바꾸려다 헷갈려서 포기했어요. ORD-eval_dataset-0004 주문은 취소로 진행해주세요. |
| 24 | 이거 그냥 취소해줘요. |
| 25 | ORD-eval_dataset-0003 원래 취소하려 했지만 이미 받았고, 최종적으로 환불 요청합니다. |
| 26 | ORD-eval_dataset-0003 환불 부탁드립니다. |
| 27 | 처음엔 교환할까 했는데요, ORD-eval_dataset-0006은 최종으로 환불만 부탁해요. |
| 28 | 사이즈가 맞지 않아 착용이 어려우니, ORD-eval_dataset-0003은 교환 대신 환불로 진행해 주세요. |
| 29 | ORD-eval_dataset-0009 환불해주세요, 파손입니다. |
| 30 | 사이즈도 안 맞고 표면에 흠집까지 있어서, ORD-eval_dataset-0006은 회수 후 환불 처리해주세요. |
| 31 | ORD-eval_dataset-0006 그냥 환불로 해줘요. |
| 32 | ORD-eval_dataset-0006 받아보니 상태가 마음에 안 들어요, 교환도 취소도 아니고 수거해서 금액만 환불해주시면 됩니다. |
| 33 | 처음엔 교환하려 했지만, ORD-eval_dataset-0009는 최종 환불로 해주세요. |
| 34 | 처음엔 교환하려 했는데 아니에요, ORD-eval_dataset-0005는 결국 환불로 할게요. |
| 35 | 주문 ORD-eval_dataset-0002는 이미 받아봤고, 취소나 환불 말고 동일 상품으로 교환 처리해주세요. |
| 36 | 사이즈가 맞지 않아 주문 ORD-eval_dataset-0002는 동일 제품으로 교환 부탁드립니다. |
| 37 | 사이즈가 너무 커서요, ORD-eval_dataset-0005 동일 상품으로 한 치수 작은 걸로 교환해주세요. |
| 38 | 옵션 바꾸려다 말았고요, 주문 ORD-eval_dataset-0002는 최종으로 같은 상품으로 교환할게요, 취소나 환불은 아닙니다. |
| 39 | ORD-eval_dataset-0005 처음엔 환불 생각했지만, 아니요 결국 같은 거 더 작은 사이즈로 교환할게요. |
| 40 | ORD-eval_dataset-0002 같은 걸로 교환해줘요. |
| 41 | 이미 수령했고 제품은 마음에 들지만 색상만 바꾸고 싶어서요, 주문 ORD-eval_dataset-0002는 환불·취소 대신 동일 모델로 교환 처리 부탁드려요. |
| 42 | ORD-eval_dataset-0005 사이즈가 커서 동일 제품 작은 사이즈로 교환 부탁드려요, 취소나 환불은 아니에요. |
| 43 | 생각 바뀌었어요—교환 아니라 ORD-eval_dataset-0001은 옵션만 바꿀게요, 이걸로 최종이에요. |
| 44 | ORD-eval_dataset-0004 옵션(사이즈)만 바꿔주세요. 취소나 환불은 원치 않습니다. |
| 45 | 사이즈가 걱정돼서요, ORD-eval_dataset-0004는 교환 말고 옵션 변경만 부탁드립니다. |
| 46 | 교환 대신 옵션만 바꾸고 싶습니다. 주문번호는 ORD-eval_dataset-0001이며, 취소나 환불은 원하지 않습니다. |
| 47 | 사이즈가 애매해서요, ORD-eval_dataset-0007은 옵션 변경만 진행해 주세요. |
| 48 | 지금 준비 중이면 ORD-eval_dataset-0004 사이즈 선택만 다른 걸로 변경해 주세요. 환불이나 취소는 안 하겠습니다. |
| 49 | 처음엔 교환하려 했지만 생각 바꿨어요. ORD-eval_dataset-0004는 최종으로 옵션 변경만 원합니다. |
| 50 | ORD-eval_dataset-0004 옵션만 바꿀 수 있을까요? |

---
*본 보고서는 `run_evaluate.py`에 의해 자동으로 생성되었습니다.*
