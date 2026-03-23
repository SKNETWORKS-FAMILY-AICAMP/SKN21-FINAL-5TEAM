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
  - `adapters/`: 다중 사이트 연동을 위한 어댑터 계층 (Python 리팩토링 완료)
  - `tools/`: 챗봇 도구 (기본 도구 + 어댑터 기반 도구)
- `benchmark/`: 합성 데이터셋 생성/품질 체크/평가기
- `chatbot_eval/`: 외부 벤치마크 실행 코드
- `data/`: 원천/가공 데이터

## 3. 어댑터 아키텍처 (Multi-Site 지원)

기존 TypeScript 기반 어댑터를 Python Pydantic 모델 기반으로 리팩토링하여 다중 사이트(Ecommerce, Food, Bilyeo)에 대한 공통 인터페이스를 제공합니다.

### 3-1. 통합 Site ID 매핑

| Site ID  | 서비스명  | 백엔드 포트 | 모듈                  |
| -------- | --------- | ----------- | --------------------- |
| `site-a` | Food      | 8002        | `src/adapters/site_a` |
| `site-b` | Bilyeo    | 5000        | `src/adapters/site_b` |
| `site-c` | Ecommerce | 8000        | `src/adapters/site_c` |

### 3-2. 주요 기능 (Adapter tools)

다음 도구들은 `site_id`를 기반으로 적절한 어댑터를 통해 각 서비스 백엔드 API를 호출합니다:

- `cancel`: 주문 취소
- `refund`: 반품/환불 접수
- `shipping`: 배송 현황 조회
- `get_order_status_adapter`: 주문 상세 상태 조회
- `search_products_adapter`: 상품 통합 검색

## 4. 실행 순서 (권장)

... (기존 내용 유지)

## 5. 실행 명령어

...

## 6. API 사용 예시 (Multi-Site)

요청 시 `site_id`를 전달하여 특정 사이트의 어댑터를 사용할 수 있습니다.

```json
{
  "message": "치킨 주문 취소해줘",
  "site_id": "site-a",
  "user_id": 1
}
```

## 7. 벤치마크/평가 실행 순서

... (기존 내용 유지)

## 8. 참고 문서

- `FASTAPI_SERVER_RUNBOOK.md`
- `benchmark/EVALUATION_GUIDE.md`
- `benchmark/DATASET_GENERATION_GUIDE.md`
- `src/adapters/README.md` (어댑터 상세 아키텍처)

uv run uvicorn chatbot.server_fastapi:app --host 127.0.0.1 --port 8100
