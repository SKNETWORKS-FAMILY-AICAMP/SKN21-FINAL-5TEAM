# 🤖 챗봇 성능 평가 보고서 (Argument Accuracy)
- **생성 일시**: 2026-03-11 16:30:24
- **평가 프레임워크**: FunctionChat-Bench
- **대상 모델**: gpt-5.2
- **실행 결과**: 1/1 벤치마크 성공
 
## 📖 평가 벤치마크 설명
본 평가는 **FunctionChat-Bench** 프레임워크를 기반으로 수행되었습니다.
 
### 1. Argument Accuracy (Dialog)
- **평가 목적**: 챗봇이 멀티턴 대화에서 필요한 인자(Argument)를 얼마나 정확하게 추출하고 올바른 Tool을 호출하는지 측정합니다.
- **핵심 지표**: 필수 인자 추출 정확도, Tool 선택 정확성, enum 값 범위 준수 여부를 검증합니다.
- **데이터셋**: `C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\chatbot_eval\benchmark\FunctionChat-Bench\data\my_eval_arg_accuracy_dialogs3.jsonl` (33개 다이얼로그)

## 📊 Argument Accuracy (Dialog) 결과
| 지표 | 결과 |
| :--- | :--- |
| **전체 테스트 케이스** | 33개 |
| **통과 수 (Pass)** | 15개 |
| **Call 정답률** | 45.5% |
| **Micro 평균** | 45.5% |

---
*본 보고서는 `run_evaluate.py`에 의해 자동으로 생성되었습니다.*
