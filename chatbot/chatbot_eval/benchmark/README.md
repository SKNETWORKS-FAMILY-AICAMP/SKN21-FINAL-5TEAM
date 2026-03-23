# 🧪 Chatbot Evaluation Benchmarks

이 디렉토리는 이커머스 챗봇의 성능을 다양한 측면에서 측정하기 위한 5가지 벤치마크 도구들을 포함하고 있습니다.

## 📂 벤치마크 폴더 개요

| 폴더명 | 주요 목적 | 평가 대상 | 주요 지표 |
| :--- | :--- | :--- | :--- |
| **[API-Bank](./API-Bank)** | JSON 생성 유효성 검증 | Tool Call 생성 능력 | JSON Valid Rate (JVR), Schema Match Rate (SMR) |
| **[FunctionChat-Bench](./FunctionChat-Bench)** | 한국어 도구 사용 능력 측정 | 함수 호출 및 인자 추출 | Argument Accuracy, Tool Selection Accuracy |
| **[KOLD](./KOLD)** | 가드레일 성능 평가 | 공격적/부적절 발화 탐지 | Accuracy, Precision, Recall, F1-Score (BLOCK 기준) |
| **[intent-bench](./intent-bench)** | 의도 분류 성능 측정 | Planner 의도 파악 능력 | Overall Accuracy, Macro F1-Score |
| **[tau-bench](./tau-bench)** | 태스크 완수 시뮬레이션 | 사용자 시나리오 완수 능력 | Task Completion Rate, Pass@k |

---

## 1. API-Bank
이커머스 챗봇이 생성하는 `tool_calls`의 JSON 형식이 올바른지, 그리고 정의된 스키마와 일치하는지 평가합니다.

- **동작 방식**: 생성된 다이얼로그 데이터셋을 기반으로 실제 모델을 호출하여 반환된 JSON 인자들의 유효성을 코드로 검증합니다.
- **실행 방법**:
  ```bash
  cd API-Bank
  python evaluate.py --model gpt-4o-mini --input_path data/my_eval_json_valid_rate_dialogs.jsonl --api_key YOUR_API_KEY
  ```

## 2. FunctionChat-Bench
한국어 대화 환경에서 챗봇의 도구 사용(Function Calling) 능력을 종합적으로 평가하는 벤치마크입니다.

- **동작 방식**: Single-turn(함수 선택) 및 Multi-turn(인자 추출 및 대화 흐름) 시나리오를 통해 모델의 정밀도를 측정합니다.
- **실행 방법**:
  ```bash
  cd FunctionChat-Bench
  # 모드 1: 기본 데이터셋, 2~4: 변형 데이터셋
  python run_evaluate.py [1|2|3|4] [trace_count] [model_name]
  ```

## 3. KOLD (Korean Offensive Language Dataset)
챗봇의 가드레일(Guardrail)이 공격적인 발화나 어뷰징 문구를 얼마나 잘 차단하는지 평가합니다.

- **동작 방식**: KOLD 데이터셋의 문장들을 가드레일 노드에 입력하여 차단 여부를 실제 라벨과 비교합니다.
- **실행 방법**:
  ```bash
  cd KOLD
  python run.py
  ```
  - 결과는 `result.md`에 리포트 형식으로 저장됩니다.

## 4. intent-bench
사용자의 입력으로부터 챗봇의 Planner가 올바른 의도(Intent)를 분류해내는지 측정합니다.

- **동작 방식**: `planner_node`를 직접 호출하여 예측된 의도가 예상된 의도와 일치하는지 확인합니다.
- **실행 방법**:
  ```bash
  cd intent-bench
  python run_intent_eval.py --model gpt-4o-mini --dataset intent_eval_dataset.jsonl
  ```

## 5. tau-bench
유저 시뮬레이터를 사용하여 실제 사용자와의 대화 시나리오를 모사하고, 챗봇이 최종 목표를 달성하는지 평가합니다.

- **동작 방식**: 에이전트와 유저 시뮬레이터 간의 다이얼로그 에피소드를 실행하고, 환경 상태 변화를 추적하여 태스크 완수 여부를 판별합니다.
- **실행 방법**:
  ```bash
  cd tau-bench
  python run.py --model gpt-4o-mini --tasks_file data/task_completion_rate_tasks.jsonl
  ```

---
*각 폴더 내부의 개별 README 파일을 참조하면 더 상세한 설정 및 지표 설명을 확인할 수 있습니다.*
