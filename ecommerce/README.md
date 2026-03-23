# ecommerce README

## 1. 프로젝트 개요

- 백엔드: FastAPI
- 프론트엔드: Next.js
- 기본 실행 포트: Backend `8000`, Frontend `3000`

## 2. 디렉토리 구조

- `backend/`
  - `app/main.py`: FastAPI 서버 시작점
  - `app/router/`: 도메인별 API 라우터
- `frontend/`: Next.js 애플리케이션
- `scripts/`: seed/eval/로그 유틸

## 3. 실행 순서

> 백엔드는 import 경로가 `ecommerce.backend...` 형태이므로 저장소 루트에서 실행 권장.

1. 루트에서 Python 의존성 설치 (`uv sync`)
2. FastAPI 서버 실행
3. 프론트 의존성 설치
4. Next.js 개발 서버 실행

## 4. 실행 명령어

### 4-1. Backend (저장소 루트에서 실행)

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM
uv sync
uv run uvicorn ecommerce.backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4-2. Frontend

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM
npm install --prefix ecommerce/frontend
npm run dev --prefix ecommerce/frontend
```

또는

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM/ecommerce/frontend
npm install
npm run dev
```

## 5. 체크 포인트

- 백엔드 선실행 후 프론트 실행
- 루트에서 백엔드 실행하지 않으면 import 오류가 발생할 수 있음
- `uv`가 없으면 먼저 설치 후 재시도
