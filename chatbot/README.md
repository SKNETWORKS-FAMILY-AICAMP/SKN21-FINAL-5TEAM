# chatbot README

## 1. 프로젝트 개요

- 목적: 챗봇 단독 FastAPI 서버 실행 + 벤치마크/평가 데이터 생성
- 서버 엔트리포인트: `server_fastapi.py`
- 주요 모듈: `src/`, `benchmark/`, `chatbot_eval/`, `data/`

## 2. 디렉토리 구조

- `server_fastapi.py`: 챗봇 단독 API 서버
  - `GET /health`
  - `POST /api/chat`
- `src/`: 그래프 워크플로우/툴/코어 설정
- `benchmark/`: 합성 데이터셋 생성/품질 체크/평가기
- `chatbot_eval/`: 외부 벤치마크 실행 코드
- `data/`: 원천/가공 데이터

## 3. 실행 순서 (권장)

1. 저장소 루트에서 Python 의존성 설치 (`uv sync`)
2. 챗봇 FastAPI 서버 실행 (포트 `8100`)
3. 헬스체크 (`/health`)
4. 채팅 API 호출 (`/api/chat`)

## 4. 실행 명령어

### 4-1. 로컬 직접 실행

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM
uv sync
uv run uvicorn chatbot.server_fastapi:app --reload --host 0.0.0.0 --port 8100
```

### 4-2. Docker 실행 (선택)

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM
docker compose -f docker-compose.adapter-lab.yml up -d --build
```

## 5. API 사용 예시

### 5-1. 단일 턴 요청

```json
{
  "message": "배송 상태 확인해줘",
  "provider": "openai",
  "user_id": 1,
  "user_name": "테스트 사용자"
}
```

### 5-2. 멀티턴 요청

이전 응답의 `conversation_id`, `state`를 다음 요청에 그대로 전달:

```json
{
  "message": "그 주문 취소도 해줘",
  "conversation_id": "이전 응답의 conversation_id",
  "previous_state": {"...": "이전 응답 state 전체"}
}
```

## 6. 벤치마크/평가 실행 순서

1. 데이터셋 생성
2. 품질 체크
3. 평가 실행

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM
uv run python -m chatbot.benchmark.build_dataset

uv run python -m chatbot.benchmark.quality_tools.quality_checker \
  --dataset ecommerce/chatbot/benchmark/datasets/functional_YYYYMMDD_HHMMSS.jsonl \
  --output ecommerce/chatbot/benchmark/datasets/functional_quality_report.json

uv run python -m chatbot.benchmark.evaluator.evaluator \
  --dataset ecommerce/chatbot/benchmark/datasets/functional_YYYYMMDD_HHMMSS.jsonl \
  --output ecommerce/chatbot/benchmark/datasets/evaluation_results.json
```

## 7. 참고 문서

- `FASTAPI_SERVER_RUNBOOK.md`
- `benchmark/EVALUATION_GUIDE.md`
- `benchmark/DATASET_GENERATION_GUIDE.md`
- `benchmark/LOGGING_GUIDE.md`
