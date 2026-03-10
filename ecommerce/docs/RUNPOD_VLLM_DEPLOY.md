# RunPod + vLLM 배포 가이드 (Qwen3.5-35B)

## 1) RunPod Pod에서 vLLM 서버 실행

아래 예시는 OpenAI 호환 API(`/v1`)로 서빙합니다.

```bash
python -m vllm.entrypoints.openai.api_server \
  --host 0.0.0.0 \
  --port 8000 \
  --model Qwen/Qwen3.5-35B-A3B \
  --gpu-memory-utilization 0.92 \
  --max-model-len 16384 \
  --served-model-name Qwen/Qwen3.5-35B-A3B \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

> 모델별 tool parser 옵션은 다를 수 있습니다. Qwen 계열에서 tool calling 포맷이 다르면 parser를 조정하세요.

## 2) 백엔드 `.env` 설정

프로젝트 루트 `.env`에 아래 값을 설정합니다.

```dotenv
LLM_PROVIDER=vllm
VLLM_BASE_URL=https://<runpod-id>-8000.proxy.runpod.net/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=Qwen/Qwen3.5-35B-A3B
```

추가로 OpenAI provider를 병행하지 않으면 `OPENAI_API_KEY`는 비워도 됩니다.

## 3) 프론트 모델 선택

채팅 UI 모델 드롭다운에서 `Qwen/Qwen3.5-35B-A3B (RunPod)`를 선택하면, 요청 provider가 `vllm`으로 전송됩니다.

## 4) 헬스체크

```bash
curl "$VLLM_BASE_URL/models"
```

정상 응답 시 백엔드에서 같은 URL로 라우팅됩니다.

## 5) 트러블슈팅

- 401/403: `VLLM_API_KEY` 값 확인 (RunPod 프록시 정책에 따라 필요)
- timeout: Pod GPU 등급 상향 또는 `max-model-len` 축소
- tool calling 이상: vLLM 실행 parser(`--tool-call-parser`) 변경
- CORS 문제: 프론트의 `NEXT_PUBLIC_API_URL`, 백엔드 CORS 허용 목록 확인
