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
