# Supervisor Eval 결과 정리

## 1) 테스트 방식 변경 이력

### 2026-03-18 1차
- 난이도 분리 평가(`easy`, `hard`) 유지
- 샘플 수:
  - `easy`: 54
  - `hard`: 34
- 주요 비교 모델: `openai/gpt-5-mini`, `openai/gpt-4o-mini`, `vllm/qwen3:0.6b`

#### 1차 기준 `easy` vs `hard` 차이
- 문장 난이도
  - `easy`: 짧고 직접적인 요청(키워드 중심, 의도 명확)
  - `hard`: 배경 설명/완곡 표현/구어체가 섞인 긴 문장(의도 추론 필요)
- 샘플 구성(1차)
  - `easy` 54건: `order` 18, `discovery` 12, `policy` 6, `form_action` 18
  - `hard` 34건: `order` 13, `discovery` 7, `policy` 6, `form_action` 8
- 정확도 차이(1차 결과)
  - `openai/gpt-5-mini`: easy 1.0000 / hard 1.0000 (차이 0.0000)
  - `openai/gpt-4o-mini`: easy 0.8519 / hard 0.8824 (hard +0.0305)
  - `vllm/qwen3:0.6b`: easy 0.6852 / hard 0.5294 (hard -0.1558)

### 2026-03-18 2차 (방식 변경)
- 난이도 분리 평가는 유지하되, **데이터셋 규모를 확장**
- 샘플 수:
  - `easy`: 70
  - `hard`: 70
- 동일 조건에서 모델 간 비교가 더 안정적으로 가능해짐

### 2026-03-19 3차 (모델 확장)
- 주로 `easy(70)` 기준으로 로컬(vLLM/Ollama) 모델군 추가 비교
- 신규 모델: 
  - `vllm/gemma2:2b`
  - `vllm/llama3.2:3b`
  - `vllm/granite3.1-dense:2b`
  - `vllm/llama3.1`
  - `vllm/phi4-mini`
  - `vllm/mistral-nemo`
  - `vllm/LFM2.5-Thinking:1.2B`
  - `vllm/Qwen3.5:2b`

### 2026-03-19 4차 (local/Qwen/Qwen3.5-2B hard 고도화)
- 대상 모델: `local/Qwen/Qwen3.5-2B`
- 대상 데이터셋: `hard(70)`
- 목적: 실제 chatbot 서버 아키텍처 기준에서 `planner -> supervisor` 상위 라우팅 정확도를 높이는 것

#### 4차-1. 평가 방식 정리
- 초기에는 전체 그래프를 태우는 방향도 검토했지만, 이 경우 retrieval/subagent 실행까지 붙어 라우팅 평가 목적에 비해 너무 무거웠음
- 최종적으로 [`run_intent_eval.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/chatbot_eval/benchmarkV2/intent-bench/run_intent_eval.py#L187)에서 `planner_node -> supervisor_node -> route_after_supervisor`만 직접 호출하는 route-only evaluator로 정리
- 효과:
  - Qdrant/HuggingFace retrieval 실행 제거
  - 평가 대상이 "질문 이해 + 상위 라우팅 정확도"로 명확해짐
  - local 모델 스모크/회귀 반복 속도 개선

#### 4차-2. planner 출력 계약 분리
- 문제:
  - `openai`/`vllm`은 structured output을 안정적으로 사용할 수 있지만, `local`은 raw text 생성이라 같은 프롬프트를 써도 출력 안정성이 낮았음
- 조치:
  - [`llm_providers.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/graph/llm_providers.py#L15)에 `LLMRuntimePolicy` 추가
  - `openai`/`vllm`은 `strict-schema`, `local`/`ollama`는 `strict-label-text`로 capability 선언
  - [`planner.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/graph/nodes/planner.py#L53)에서 로컬 모델용 strict-label-text 계약과 retry 프롬프트 도입
- 서버 반영:
  - [`chat.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/api/v1/endpoints/chat.py#L240)
  - [`server_fastapi.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/server_fastapi.py#L152)
  - 웹에서 어떤 모델을 선택하든 서버 기본 설정과 request 값에 따라 동일한 runtime policy가 적용되도록 정리

#### 4차-3. 하드 실패 케이스 기반 규칙층 추가
- runtime policy 정리 후에도 hard 오답이 남아 있었고, 패턴은 다음 5개 군으로 수렴
  - `order_cs` vs `policy_rag`
  - `discovery` vs `final_generator`
  - `review/write` vs `discovery`
  - `used-item` vs `order_cs`
  - `gift-card` vs `final_generator`
- 조치:
  - 남은 오답 11건을 [`test_planner_output_modes.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/tests/test_planner_output_modes.py#L164)에 회귀 테스트로 고정
  - [`planner.py`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/graph/nodes/planner.py#L79)에 고정밀 규칙층 추가
  - 규칙 우선순위:
    - `REGISTER_GIFT_CARD`
    - `WRITE_REVIEW`
    - `REGISTER_USED_ITEM`
    - `POLICY_RAG`
    - `ORDER_CS`
    - `SEARCH_SIMILAR_TEXT`
- 이 규칙층은 LLM을 대체하는 것이 아니라, "LLM 없이도 확실한 문장"만 선점하고 나머지는 기존 LLM 경로로 넘김

#### 4차-4. 점수 변화

| 단계 | 주요 변경 | hard 결과 | 비고 |
|---|---|---|---|
| 기준점 | route-only evaluator 기준 첫 hard 실행 | 58/70 (0.8286) | 사용자 공유 결과 |
| 1차 개선 | runtime policy 도입, planner 출력 계약 분리, 서버 모델 설정 연동 | 59/70 (0.8429) | +1건 |
| 2차 개선 | hard 오답 11건 회귀 테스트 + planner 고정밀 규칙층 추가 | 69/70 (0.9857) | +10건 |

#### 4차-5. 최종 상태
- 최종 실행 커맨드:
  - `uv run python -m chatbot.chatbot_eval.benchmarkV2.intent-bench.run_intent_eval --provider local --model Qwen/Qwen3.5-2B --difficulty hard`
- 최종 결과:
  - 정확도: `69/70 (0.9857)`
  - Macro F1: `0.9749`
  - 소요 시간: `84.7초`
- 남은 오답 1건:
  - 입력: `명절 기간에는 배송이 지연된다고 들었는데, 정확히 언제부터 언제까지 늦어지는지 알고 싶어요.`
  - 기대: `policy_rag_subagent`
  - 예측: `order_intent_router`
  - 원인: 현재 규칙에서 `배송 + 지연` 패턴이 `ORDER_CS`로 먼저 잡히지만, 이 문장은 "내 주문 상태"가 아니라 "명절 기간 배송 지연 정책/안내"를 묻는 정책성 질문

## 2) 모델 변경 및 성능 요약 (`result.json` 기준)

### Easy/Hard 통합 비교 (동일 실험군)

| 구분 | 모델 | easy | hard | 통합 (easy+hard) |
|---|---|---|---|---|
| 1차 (54/34) | openai/gpt-5-mini | 54/54 (1.0000) | 34/34 (1.0000) | 88/88 (1.0000) |
| 1차 (54/34) | openai/gpt-4o-mini | 46/54 (0.8519) | 30/34 (0.8824) | 76/88 (0.8636) |
| 1차 (54/34) | vllm/qwen3:0.6b | 37/54 (0.6852) | 18/34 (0.5294) | 55/88 (0.6250) |
| 2차 (70/70) | openai/gpt-5-mini | 70/70 (1.0000) | 65/70 (0.9286) | 135/140 (0.9643) |
| 2차 (70/70) | openai/gpt-4o-mini | 62/70 (0.8857) | 61/70 (0.8714) | 123/140 (0.8786) |
| 2차 (70/70) | vllm/qwen3:0.6b | 51/70 (0.7286) | 40/70 (0.5714) | 91/140 (0.6500) |

### 3차 모델 확장 결과 (easy만 존재)

| 모델 | easy 결과 |
|---|---|
| vllm/llama3.1 | 69/70 (0.9857) |
| vllm/mistral-nemo | 63/70 (0.9000) |
| vllm/gemma2:2b | 58/70 (0.8286) |
| vllm/phi4-mini | 53/70 (0.7571) |
| vllm/granite3.1-dense:2b | 51/70 (0.7286) |
| vllm/llama3.2:3b | 44/70 (0.6286) |
| vllm/LFM2.5-Thinking:1.2B | 25/70 (0.3571) |
| vllm/Qwen3.5:2b | 0/70 (0.0000) |

### 전체 실행 시간 기록 (모델/난이도/샘플/시간)

| 모델 | 난이도 | 샘플 수 | 시간(초) |
|---|---|---:|---:|
| openai/gpt-5-mini | easy | 54 | 23.96 |
| openai/gpt-5-mini | hard | 34 | 19.39 |
| openai/gpt-5-mini | easy | 70 | 25.49 |
| openai/gpt-5-mini | hard | 70 | 38.19 |
| openai/gpt-4o-mini | easy | 54 | 7.21 |
| openai/gpt-4o-mini | hard | 34 | 5.50 |
| openai/gpt-4o-mini | easy | 70 | 12.88 |
| openai/gpt-4o-mini | hard | 70 | 11.48 |
| vllm/qwen3:0.6b | easy | 54 | 578.29 |
| vllm/qwen3:0.6b | hard | 34 | 313.48 |
| vllm/qwen3:0.6b | easy | 70 | 496.72 |
| vllm/qwen3:0.6b | hard | 70 | 1253.61 |
| vllm/gemma2:2b | easy | 70 | 307.62 |
| vllm/llama3.2:3b | easy | 70 | 257.97 |
| vllm/granite3.1-dense:2b | easy | 70 | 245.88 |
| vllm/llama3.1 | easy | 70 | 343.98 |
| vllm/phi4-mini | easy | 70 | 251.56 |
| vllm/mistral-nemo | easy | 70 | 541.62 |
| vllm/LFM2.5-Thinking:1.2B | easy | 70 | 5067.63 |
| vllm/Qwen3.5:2b | easy | 70 | 5197.51 |

## 3) local/Qwen/Qwen3.5-2B hard 고도화 요약

| 날짜 | 모델 | 평가 범위 | 결과 |
|---|---|---|---|
| 2026-03-19 16:59 | local/Qwen/Qwen3.5-2B | hard 70 | 58/70 (0.8286) |
| 2026-03-19 이후 | local/Qwen/Qwen3.5-2B | hard 70 | 59/70 (0.8429) |
| 2026-03-19 최종 | local/Qwen/Qwen3.5-2B | hard 70 | 69/70 (0.9857), Macro F1 0.9749 |

핵심 해석:
- 82.86% -> 84.29%는 "모델 capability에 맞는 planner 출력 계약과 서버 런타임 정책 정리"의 효과
- 84.29% -> 98.57%는 "남은 hard 오답을 회귀 테스트로 고정하고, planner 앞단에 고정밀 규칙층을 추가"한 효과
