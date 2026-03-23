# Chatbot FastAPI 서버 실행 가이드

## 1) Docker 기반(권장)

### 전체 스택 실행
- `docker compose -f docker-compose.adapter-lab.yml up -d --build`

### 챗봇 서버 상태 확인
- `GET http://localhost:8100/health`

### 채팅 요청 예시
- `POST http://localhost:8100/api/chat`
- Body:
```json
{
  "message": "배송 상태 확인해줘",
  "provider": "openai",
  "user_id": 1,
  "user_name": "테스트 사용자"
}
```

## 2) 로컬 직접 실행

루트에서:
- `uv sync`
- `uv run uvicorn chatbot.server_fastapi:app --reload --host 0.0.0.0 --port 8100`

## 3) 멀티턴 대화

응답의 `state`와 `conversation_id`를 다음 요청에 다시 전달하면 됩니다.

```json
{
  "message": "그 주문 취소도 해줘",
  "conversation_id": "이전 응답의 conversation_id",
  "previous_state": {"...": "이전 응답 state 전체"}
}
```

## 4) 사이트 폴더 불변성 검증

- `bash scripts/verify_site_immutable.sh`

테스트 전/후에 실행해서 `ecommerce`, `bilyeo`, `food` 폴더가 변경되지 않았는지 확인합니다.
