# Repository Guidelines

## 빌드, 테스트, 개발 명령어

- 의존성 설치(루트): `uv sync`
<<<<<<< HEAD
- 백엔드 실행(루트): `uv run uvicorn ecommerce.platform.backend.app.main:app --reload --host 0.0.0.0 --port 8000`
=======
- 백엔드 실행(루트): `uv run uvicorn ecommerce.backend.app.main:app --reload --host 0.0.0.0 --port 8000`
>>>>>>> 0292cc4ddd73d5bbaa321534bdb53adc66b09ada
- 프론트엔드 실행:
  - `npm run dev --prefix ecommerce/frontend`
- 통합 실행(도커): `docker compose up -d --build`

## 커밋 및 PR 가이드라인

- 최근 이력은 `이름_변경요약` 또는 `이름-주제설명` 형태가 많습니다(예: `준석_배송지UI안뜨게 수정`).
- 권장 커밋 형식: `영역: 변경 요약` (예: `use/usrs: 로그인 이력 metadata 저장 수정`).
- PR은 자동으로 진행하지 않습니다.

## 코드 수정 규칙

- 사용자의 허가 없이 **절대** 코드를 함부로 수정하지 않습니다.