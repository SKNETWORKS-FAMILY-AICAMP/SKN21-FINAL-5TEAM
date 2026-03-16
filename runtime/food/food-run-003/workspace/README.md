# food README

## 1. 프로젝트 개요

- 백엔드: Django
- 프론트엔드: React (react-scripts)
- 기본 실행 포트: Backend `8000`, Frontend 기본 포트(일반적으로 `3000`)

## 2. 디렉토리 구조

- `backend/`
  - `foodshop/`: Django 설정/URL/WSGI
  - `orders/`, `products/`, `users/`: 도메인 앱
- `frontend/`: React 애플리케이션
- `seed/`: CSV 생성/초기 데이터 유틸

## 3. 실행 순서

1. `backend` 가상환경 생성 및 의존성 설치
2. Django 마이그레이션
3. Django 서버 실행
4. `frontend` 의존성 설치
5. `frontend` 개발 서버 실행

## 4. 실행 명령어

### 4-1. Backend

```bash
cd food/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000
```

### 4-2. Frontend

```bash
cd food/frontend
npm install
npm run dev
```

## 5. 체크 포인트

- 마이그레이션(`migrate`) 먼저 실행 후 서버 기동
- 프론트는 백엔드 실행 이후에 올리는 것을 권장
- 포트 충돌 시 실행 포트 변경 후 재시도
