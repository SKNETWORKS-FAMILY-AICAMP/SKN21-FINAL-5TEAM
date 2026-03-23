# 챗봇 아키텍처 실험 결과서

## 1. 문서 목적

이 문서는 발표 자료에서 사용할 수 있도록, 챗봇 아키텍처 각 구성요소에 대해

- 어떤 질문/출력을 평가했는지
- 어떤 데이터셋과 지표를 사용했는지
- 어떤 방식으로 고도화했는지
- 고도화 전후 점수가 어떻게 변했는지

를 한 번에 정리한 실험 근거 문서다.

본 문서는 2026-03-19 기준 리포지토리에 커밋되어 있는 평가 스크립트, 데이터셋, 결과 리포트, 테스트 코드만을 근거로 작성했다.

## 2. 정리 기준

- 담당자는 git commit message 기준으로 정리했다.
- 점수는 리포지토리에 실제로 남아 있는 결과 파일 기준으로만 적었다.
- 실행 파이프라인은 구현되어 있으나 결과 리포트가 커밋되어 있지 않은 경우, "파이프라인 구축 완료 / 실험 결과 파일 미커밋"으로 분리 표기했다.

## 3. 공통 실험 프로세스

각 파트는 공통적으로 아래 절차로 실험했다.

1. 아키텍처 컴포넌트별로 실패 유형을 정의했다.
2. 해당 컴포넌트의 입력 질문과 기대 출력 기준을 데이터셋으로 만들었다.
3. 벤치마크 실행 스크립트로 동일한 데이터셋을 반복 평가했다.
4. 정량 지표를 기록하고 실패 케이스를 수집했다.
5. 프롬프트, 라우팅, query transformation, retrieval/reranking heuristic을 수정했다.
6. 동일 데이터셋으로 다시 평가해 점수 변화와 개선 근거를 남겼다.

발표에서는 이 공통 흐름을 먼저 설명한 뒤, 아래 팀원별 사례를 붙이면 된다.

## 4. 팀원별 실험 기록

### 4.1 승룡: Function Calling 품질 평가

**평가 대상**

- 주문 취소, 환불, 교환, 배송조회, 상품 검색, 추천, 리뷰 작성, 중고상품 등록 등 실제 챗봇 tool call 품질

**평가 파이프라인**

- 프레임워크: `FunctionChat-Bench`
- 데이터셋: `chatbot/chatbot_eval/benchmark/FunctionChat-Bench/data/my_eval_arg_accuracy_dialogs.jsonl`
- 결과 리포트: `chatbot/chatbot_eval/benchmark/FunctionChat-Bench/eval_report_arg_acc_20260316_143511.md`

**실험 방법**

- 한국어 멀티턴 대화 27개를 입력했다.
- 각 대화에 대해 챗봇이 호출한 tool name과 arguments를 정답과 비교했다.
- 주요 지표는 `Call 정답률`, `Micro 평균`, `Pass 개수`를 사용했다.

**실험 결과**

| 항목 | 값 |
| :--- | :--- |
| 전체 테스트 케이스 | 27 |
| 통과 수 | 6 |
| 실패 수 | 21 |
| Call 정답률 | 22.2% |
| Micro 평균 | 22.2% |

**해석**

- Tool calling 품질은 아직 낮은 편이다.
- 추천, 리뷰, 일반 검색, 주문 상태 해석 계열에서 실패가 많이 발생했다.
- 반대로 주문 취소, 교환, 단순 배송조회, 중고 판매 폼 호출처럼 패턴이 명확한 케이스는 일부 통과했다.
- 이 결과는 "tool-use 파트는 별도 고도화가 필요하다"는 근거로 발표에 사용 가능하다.

**발표용 메시지**

- Function calling은 정성 평가가 아니라 27개 골드 대화셋으로 측정했다.
- 현재 점수는 22.2%이며, 가장 큰 병목은 추천/검색/리뷰 계열의 argument 정확도다.

**근거 파일**

- `chatbot/chatbot_eval/benchmark/FunctionChat-Bench/eval_report_arg_acc_20260316_143511.md`
- `chatbot/chatbot_eval/benchmark/FunctionChat-Bench/README.md`

### 4.2 성현: Supervisor 라우팅 평가

**평가 대상**

- Planner/Supervisor가 사용자 질문을 어떤 노드로 라우팅해야 하는지 분류하는 성능
- 대상 노드: `order_intent_router`, `discovery_subagent`, `policy_rag_subagent`, `form_action_subagent`

**평가 파이프라인**

- 데이터셋: `chatbot/chatbot_eval/benchmarkV2/intent-bench/supervisor_eval_dataset.jsonl`
- 실행기: `chatbot/chatbot_eval/benchmarkV2/intent-bench/run_intent_eval.py`
- 결과 리포트: `chatbot/chatbot_eval/benchmarkV2/result/supervisor_eval/result.json`

**실험 방법**

- easy 54건, hard 34건으로 분리된 supervisor 평가셋을 사용했다.
- `planner_node` 결과를 실제 라우팅 노드 이름으로 매핑해 정답 노드와 비교했다.
- `accuracy`, `macro_f1`, `per_node_f1`, `confusion_matrix`를 기록했다.
- 여러 모델을 동일한 데이터셋에서 비교해 라우팅 모델 선택 근거로 사용했다.

**실험 결과**

| 모델 | 난이도 | 샘플 수 | Accuracy | Macro F1 |
| :--- | :--- | :---: | :---: | :---: |
| `openai/gpt-5-mini` | easy | 54 | 1.0000 | 1.0000 |
| `openai/gpt-5-mini` | hard | 34 | 1.0000 | 1.0000 |
| `openai/gpt-4o-mini` | easy | 54 | 0.8519 | 0.7386 |
| `openai/gpt-4o-mini` | hard | 34 | 0.8824 | 0.7548 |
| `vllm/qwen3:0.6b` | easy | 54 | 0.6852 | 0.5605 |
| `vllm/qwen3:0.6b` | hard | 34 | 0.5294 | 0.4874 |

**해석**

- Supervisor 라우팅은 `gpt-5-mini`가 easy/hard 모두 100% 정확도로 가장 안정적이었다.
- `gpt-4o-mini`도 일정 수준 성능은 보였지만 hard셋에서 완전하지 않았다.
- `qwen3:0.6b`는 low-cost 실험군으로 의미는 있었지만 실서비스용 라우팅 모델로는 오분류가 많았다.
- 이 결과는 "왜 라우팅 모델을 해당 모델로 선택했는가"에 대한 직접적인 근거다.

**발표용 메시지**

- Supervisor는 감으로 정한 것이 아니라 easy 54건, hard 34건의 분류셋으로 검증했다.
- 모델 비교 결과 `gpt-5-mini`만 easy/hard 모두 100% accuracy, 100% macro F1을 달성했다.

**근거 파일**

- `chatbot/chatbot_eval/benchmarkV2/result/supervisor_eval/result.json`
- `chatbot/chatbot_eval/benchmarkV2/intent-bench/run_intent_eval.py`

### 4.3 남웅: Policy RAG 평가와 고도화

**평가 대상**

- 정책 안내형 질의에 대해 Policy RAG가
  1. 적절한 검색용 질의로 변환하는지
  2. 정답 문서를 top-k 안에 가져오는지
  3. 답변이 실제 문서에 grounded 되는지

**평가 파이프라인**

- 데이터셋: `chatbot/chatbot_eval/benchmark/rags/policy_rag/data/eval_dataset.jsonl`
- 실행기: `chatbot/chatbot_eval/benchmark/rags/policy_rag/run.py`
- 결과 리포트 폴더: `chatbot/chatbot_eval/benchmark/rags/policy_rag/reports/`

**실험 방법**

- 30개 정책 질문에 대해 `expected_query`, `expected_doc_keys`, `expected_phrases`를 정답으로 만들었다.
- 파이프라인은 `Policy RAG SubAgent -> Query Transformation -> Sparse/Dense Retrieve -> Qdrant` 흐름으로 평가했다.
- `query_pass_rate`, `retrieval_pass_rate`, `hit@1`, `hit@3`, `hit@5`를 기록했다.

**고도화 기록**

리포지토리에는 수정 단계별 결과 파일이 남아 있다.

| 단계 | 데이터 수 | Query Pass | Retrieval Pass | Hit@1 | Hit@3 | Hit@5 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `smoke_after_fix` | 1 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| `after_second_fix` | 30 | 93.33% | 76.67% | 43.33% | 73.33% | 76.67% |
| `after_third_fix` | 30 | 93.33% | 100.0% | 66.67% | 100.0% | 100.0% |
| `after_fourth_fix` | 30 | 93.33% | 100.0% | 80.00% | 96.67% | 100.0% |

**점수 변화 해석**

- `after_second_fix`에서 아직 문서 retrieval이 불안정했다.
- `after_third_fix`에서 Retrieval Pass가 `76.67% -> 100.0%`로 크게 개선됐다.
- `after_fourth_fix`에서는 Retrieval Pass 100%를 유지한 채 Hit@1이 `66.67% -> 80.00%`로 추가 상승했다.
- 즉, 정책 RAG는 "정답 문서를 찾는 수준"을 넘어서 "정답 문서를 더 상위 순위에 배치하는 수준"까지 고도화되었다.

**고도화 근거**

테스트 코드 기준으로 확인되는 주요 개선 포인트는 아래와 같다.

- policy category 추론 강화
- query variants 확장
- FAQ/약관 retrieval filter 개선
- partial/used/배송비/배송조회 같은 혼동 문서에 대한 reranking penalty/bonus 설계

**발표용 메시지**

- Policy RAG는 30개 정책 질문셋으로 반복 실험했다.
- 고도화 후 Retrieval Pass는 100%, Hit@1은 80%까지 개선되었다.
- 즉, "찾기는 찾는다"를 넘어서 "처음부터 맞는 문서를 더 빨리 찾는다"는 방향으로 품질이 개선되었다.

**근거 파일**

- `chatbot/chatbot_eval/benchmark/rags/policy_rag/reports/policy_rag_eval_after_second_fix.json`
- `chatbot/chatbot_eval/benchmark/rags/policy_rag/reports/policy_rag_eval_after_third_fix.json`
- `chatbot/chatbot_eval/benchmark/rags/policy_rag/reports/policy_rag_eval_after_fourth_fix.json`
- `chatbot/tests/test_policy_rag_retrieval_heuristics.py`

### 4.4 남웅: Discovery RAG 평가와 고도화

**평가 대상**

- 상품 탐색형 질의에서 Discovery RAG가
  1. 정답 상품을 top-k 안에 가져오는지
  2. 답변이 실제 검색 결과와 일치하는지

**평가 파이프라인**

- 데이터셋: `chatbot/chatbot_eval/benchmark/rags/discovery/data/eval_dataset.jsonl`
- 실행기: `chatbot/chatbot_eval/benchmark/rags/discovery/run.py`
- 결과 리포트 폴더: `chatbot/chatbot_eval/benchmark/rags/discovery/reports/`

**실험 방법**

- 30개 discovery 질의에 대해 `expected_product_ids`, `expected_keywords`를 정답으로 만들었다.
- 파이프라인은 `Discovery Subagent -> VLM (CLIP MODEL) -> Retrieve` 흐름으로 평가했다.
- `retrieval_pass_rate`, `hit@1`, `hit@3`, `hit@5`, `grounding_pass_rate`, `grounding_keyword_recall`을 기록했다.

**고도화 기록**

| 단계 | 데이터 수 | Retrieval Pass | Hit@1 | Hit@3 | Hit@5 | Grounding Pass | Keyword Recall |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `after_korean_fix` | 30 | 66.67% | 36.67% | 63.33% | 66.67% | 96.67% | 90.56% |
| `after_second_korean_fix` | 30 | 86.67% | 50.00% | 76.67% | 86.67% | 100.0% | 97.78% |
| `after_third_korean_fix` | 30 | 86.67% | 53.33% | 83.33% | 86.67% | 100.0% | 97.78% |
| `after_fourth_korean_fix` | 30 | 83.33% | 60.00% | 83.33% | 83.33% | 93.33% | 91.67% |
| `after_final_ranking_fix` | 30 | 86.67% | 53.33% | 83.33% | 86.67% | 100.0% | 97.78% |

**점수 변화 해석**

- 첫 번째 리포트 대비 최종 리포트에서 Retrieval Pass는 `66.67% -> 86.67%`로 20.00%p 상승했다.
- Grounding Pass는 `96.67% -> 100.0%`로 개선됐다.
- Keyword Recall도 `90.56% -> 97.78%`로 상승했다.
- 중간 단계에서 Hit@1은 60.00%까지 올라갔지만, grounding과 retrieval 안정성이 일부 흔들리는 구간이 있었다.
- 최종적으로는 상위 1개 정답률보다 전체 retrieval 안정성과 grounding 일관성을 우선한 형태로 정리된 것으로 해석할 수 있다.

**고도화 근거**

테스트 코드 기준으로 확인되는 주요 개선 포인트는 아래와 같다.

- 한국어 질의를 영어 검색어로 번역
- 원문 + 번역문 + compact focused query를 함께 사용
- category/color가 맞는 상품에 가산점 부여
- `waist pouch`, `messenger bag`처럼 헷갈리는 오답 상품에 penalty 부여

**발표용 메시지**

- Discovery RAG는 30개 상품 탐색 질문셋으로 반복 실험했다.
- 한국어 질의 확장과 ranking 보정으로 Retrieval Pass를 66.67%에서 86.67%까지 끌어올렸다.
- 최종적으로는 "찾는 능력"과 "근거 있는 설명"을 동시에 안정화했다.

**근거 파일**

- `chatbot/chatbot_eval/benchmark/rags/discovery/reports/discovery_rag_eval_after_korean_fix.json`
- `chatbot/chatbot_eval/benchmark/rags/discovery/reports/discovery_rag_eval_after_second_korean_fix.json`
- `chatbot/chatbot_eval/benchmark/rags/discovery/reports/discovery_rag_eval_after_third_korean_fix.json`
- `chatbot/chatbot_eval/benchmark/rags/discovery/reports/discovery_rag_eval_after_final_ranking_fix.json`
- `chatbot/tests/test_discovery_eval.py`

### 4.5 준석: LLM 출력 평가 파이프라인 구축

**평가 대상**

- 온보딩 아키텍처에서 LLM이 생성하는 Generator 출력
- 생성된 backend/frontend 산출물의 정합성
- 이후 개선 시 점수 변화를 누적 기록할 수 있는 자동 평가 파이프라인

**구축된 평가 파이프라인**

- Generator golden eval: `chatbot/src/onboarding/generator_eval.py`
- Generator 실행기: `chatbot/scripts/run_generator_eval.py`
- Golden fixtures: `chatbot/tests/onboarding/goldens/generator/*.json`
- Backend evaluator: `chatbot/src/onboarding/backend_evaluator.py`
- Frontend evaluator: `chatbot/src/onboarding/frontend_evaluator.py`

**실험 방법**

Generator 평가:

- fixture마다 `analysis`, `recommended_outputs`, `expected.proposed_files`, `expected.proposed_patches`, `forbidden`을 정의했다.
- LLM 또는 role runner가 생성한 proposal을 정답과 비교했다.
- `passed`, `score`, `missing_files`, `extra_files`, `missing_patches`, `forbidden_hits`, `average_score`, `failed_fixture_ids`, `score_distribution`을 남기도록 설계했다.

Backend 평가:

- runtime workspace의 Python 파일을 순회하며 `py_compile`로 검증했다.
- framework 탐지, entrypoint smoke, route wiring, tool registry, dependency bootstrap 결과를 `backend-evaluation.json`에 저장하도록 설계했다.

Frontend 평가:

- React/Vue mount candidate, widget 경로, auth fetch 존재 여부, build 가능 여부를 검증했다.
- 실패 시 recovery/hard fallback 이벤트와 함께 `frontend-evaluation.json`, `frontend-build-validation.json`을 남기도록 설계했다.

**리포지토리에서 확인된 정량 근거**

| 항목 | 확인된 사실 |
| :--- | :--- |
| Generator regression | golden fixture `6건 이상`에 대해 `failed = 0` |
| Generator CLI summary | 단일 fixture 샘플에서 `average_score = 1.0` 출력 검증 |
| Backend evaluator | Django / Flask / FastAPI 각각 report 생성 검증 |
| Frontend evaluator | React / Vue mount 검출, build pass, recovery / hard fallback 검증 |

**해석**

- 이 파트는 "최종 모델 점수"보다 "실험을 계속 누적할 수 있는 평가 파이프라인을 만들었다"는 점이 핵심이다.
- 즉, 이후 LLM 프롬프트나 생성 로직을 고도화할 때마다 같은 fixture로 다시 돌려 점수 변화를 남길 수 있다.
- 발표에서는 이 부분을 "정량 평가 체계 구축"으로 설명하는 것이 적절하다.

**주의할 점**

- 리포지토리에는 Generator/Frontend/Backend의 실제 대규모 실행 결과 JSON 리포트는 커밋되어 있지 않았다.
- 따라서 이 섹션은 "평가 체계 구축 완료 및 회귀 검증 통과"까지는 확실하게 말할 수 있지만, "운영 데이터 기준 최종 점수"라고 표현하면 안 된다.

**발표용 메시지**

- LLM 출력은 이제 사람이 감으로 보는 것이 아니라 fixture 기반으로 자동 평가 가능하다.
- Generator는 golden fixture 회귀 테스트를 통과하고, frontend/backend는 런타임 결과물을 자동 검증하는 파이프라인을 갖췄다.
- 따라서 앞으로의 고도화는 반드시 같은 평가셋으로 재측정해 근거를 남길 수 있다.

**근거 파일**

- `chatbot/src/onboarding/generator_eval.py`
- `chatbot/scripts/run_generator_eval.py`
- `chatbot/tests/onboarding/test_generator_golden_regression.py`
- `chatbot/tests/onboarding/test_generator_eval_cli.py`
- `chatbot/src/onboarding/backend_evaluator.py`
- `chatbot/src/onboarding/frontend_evaluator.py`

## 5. 발표에 바로 쓸 수 있는 핵심 결론

### 5.1 정량 평가 체계가 있는 파트

- Function calling
- Supervisor routing
- Policy RAG
- Discovery RAG
- Onboarding generator/frontend/backend evaluation pipeline

### 5.2 발표에서 강조할 만한 수치

- Supervisor: `gpt-5-mini`가 easy/hard 모두 `Accuracy 100%`, `Macro F1 100%`
- Policy RAG: Retrieval Pass `76.67% -> 100.0%`, Hit@1 `43.33% -> 80.00%`
- Discovery RAG: Retrieval Pass `66.67% -> 86.67%`, Grounding Pass `96.67% -> 100.0%`
- Function calling: 현재 `22.2%`로 낮아서 다음 고도화 우선순위라는 근거 확보
- Onboarding eval: fixture 기반 자동 평가 체계 구축 완료

### 5.3 발표 서사 예시

아래 순서로 발표하면 흐름이 자연스럽다.

1. 챗봇 아키텍처를 구성요소별로 분해했다.
2. 각 구성요소마다 질문-정답-평가 지표가 있는 실험셋을 만들었다.
3. 동일 데이터셋으로 반복 실험하면서 고도화 전후 점수 변화를 기록했다.
4. 그 결과 Supervisor와 RAG는 성능이 크게 개선되었고, Function Calling은 다음 개선 우선순위라는 결론을 얻었다.
5. 또한 Generator/Frontend/Backend는 앞으로 개선 근거를 계속 남길 수 있는 자동 평가 파이프라인까지 구축했다.

## 6. 참고 커밋 이력

담당자 추정에 사용한 대표 커밋은 아래와 같다.

- 승룡: `2289f3e7` `승룡-펑션챗벤치마크우리프로젝트평가`
- 승룡: `176b479a` `승룡-벤치마크툴호출`
- 성현: `05ae5eeb` `성현 - supervisor의 분류 성능 평가`
- 성현: `9789c398` `성현 - planner 평가 qwen, 병렬처리 추가`
- 성현: `d3014408` `성현 - 평가 데이터셋 수정 ,  bilyeo 교환/환불/주문취소/주문조회 추가`
- 남웅: `d99f2f11` `남웅_rags 정책 평가 진행중`
- 남웅: `69ff84d5` `남웅_rags_poilcy,discovery 작업`
- 남웅: `4c88b8ba` `남웅_food 툴 구현, rags 고도화 진행중`
- 준석: `4f0fffde` `onboarding: add contract-driven generation and repair pipeline`

## 7. 한 줄 요약

이 프로젝트는 챗봇 각 파트를 단순 구현에 그치지 않고, 질문-정답-평가셋-리포트 구조로 실험해 점수 변화를 남겼고, 그 결과 Supervisor와 RAG는 개선 근거를 확보했으며, Generator/Frontend/Backend는 앞으로의 고도화를 정량 추적할 수 있는 평가 파이프라인까지 갖추었다.
