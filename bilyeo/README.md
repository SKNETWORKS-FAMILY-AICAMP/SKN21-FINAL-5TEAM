# bilyeo README

## 1. 프로젝트 개요

- 백엔드: Flask
- 프론트엔드: Vue + Vite
- 기본 실행 포트: Backend `5000`, Frontend(Vite) 기본 포트

## 2. 디렉토리 구조

- `backend/`
  - `app.py`: Flask 서버 시작점
  - `routes/`: 인증/상품/주문 API
  - `models/`: 데이터 모델
- `frontend/`: Vue 애플리케이션
- `scripts/`: 크롤링/초기화 유틸

## 3. 실행 순서

1. `backend` 가상환경 생성 및 의존성 설치
2. `backend` 서버 실행
3. `frontend` 의존성 설치
4. `frontend` 개발 서버 실행

## 4. 실행 명령어

### 4-1. Backend

```bash
cd bilyeo/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### 4-2. Frontend

```bash
cd bilyeo/frontend
npm install
npm run dev
```

## 5. 체크 포인트

- `.env` 파일이 `bilyeo/.env`에 존재하는지 확인
- 백엔드가 먼저 떠 있는 상태에서 프론트를 실행
- 포트 충돌 시 실행 포트 변경 후 재시도
