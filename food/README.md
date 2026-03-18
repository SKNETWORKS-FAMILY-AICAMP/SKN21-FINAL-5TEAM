# Food

`food`는 YAAM Food Shop 예제 서비스입니다. React 프론트엔드와 Django REST 백엔드로 구성되어 있고, 로그인 세션 기반으로 주문 조회와 주문 CS 기능을 제공합니다.

## 구성

- 백엔드: Django + Django REST Framework
- 프론트엔드: React 18 + `react-scripts`
- 데이터베이스: SQLite
- 기본 포트
  - 백엔드: `8000`
  - 프론트엔드: `3000`

## 현재 지원 기능

- 상품 목록 조회
- 이메일/비밀번호 로그인
- 세션 쿠키(`session_token`) 기반 사용자 확인
- 내 주문 조회
- 주문 상세 조회
- 주문 취소
- 환불 요청
- 교환 요청
- 주문/환불/교환 관련 프론트 내장 챗봇 UI

## 디렉토리 구조

- `backend/`
  - `foodshop/`: Django 설정, URL, WSGI/ASGI
  - `orders/`: 주문 조회/취소/환불/교환 API
  - `products/`: 상품 API 및 모델
  - `users/`: 로그인, 로그아웃, 세션 확인 API
  - `seed/`: 초기 데이터 스크립트와 CSV
- `frontend/`
  - `src/pages/`: 로그인, 상품, 주문 페이지
  - `src/components/chatbot/`: 주문 챗봇 UI
  - `src/context/`: 인증 상태 관리

## 실행 방법

### 1. 백엔드 실행

```bash
cd food/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000
```

macOS/Linux라면 활성화 명령은 아래를 사용하면 됩니다.

```bash
source .venv/bin/activate
```

### 2. 프론트엔드 실행

```bash
cd food/frontend
npm install
npm run dev
```

프론트엔드는 기본적으로 `http://127.0.0.1:8000` 백엔드를 프록시하도록 설정되어 있습니다.

## 주요 API

- `GET /api/products/`
- `GET /api/orders/`
- `GET /api/orders/{order_id}/`
- `POST /api/orders/{order_id}/actions/`
- `POST /api/users/login/`
- `POST /api/users/logout/`
- `GET /api/users/me/`

## 주문 액션 요청 예시

`POST /api/orders/{order_id}/actions/`

```json
{
  "action": "cancel"
}
```

지원 action 값:

- `status`
- `pay`
- `cancel`
- `refund`
- `exchange`

주의:

- 주문 API는 로그인된 사용자 본인 주문만 조회할 수 있습니다.
- 주문 조회/취소/환불/교환은 `session_token` 쿠키가 있어야 정상 동작합니다.

## 테스트

주문 API 검증:

```bash
uv run python food/backend/manage.py test orders
```

## 개발 메모

- 백엔드 마이그레이션 후 서버를 띄우는 순서를 권장합니다.
- CORS는 기본적으로 `http://localhost:3000`을 허용합니다.
- 프론트 챗봇과 주문 페이지는 동일한 주문 API를 사용합니다.
