# Repository Guidelines

## 프로젝트 구조 및 모듈 구성

- `ecommerce/platform/backend/app`: FastAPI 백엔드(라우터, 스키마, 모델, 인증, DB).
- `ecommerce/platform/frontend/app`: Next.js(App Router) 프론트엔드 화면/컴포넌트.
- `ecommerce/chatbot/src`: LangGraph/LangChain 기반 챗봇 코어 및 도구 로직.
- 루트 인프라 파일: `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend`, `nginx.conf`.

## 빌드, 테스트, 개발 명령어

- 의존성 설치(루트): `uv sync`
- 백엔드 실행(루트): `uv run uvicorn ecommerce.platform.backend.app.main:app --reload --host 0.0.0.0 --port 8000`
- 프론트엔드 실행:
  - `npm run dev --prefix ecommerce/platform/frontend`
- 프론트엔드 빌드/실행: `npm run build`, `npm run start`
- 린트: `npm run lint --prefix ecommerce/platform/frontend`
- 통합 실행(도커): `docker compose up -d --build`

## 코딩 스타일 및 네이밍 규칙

- 라우터 구조는 기존 패턴(`router.py`, `crud.py`, `schemas.py`, `models.py`)을 유지.
- 파일/폴더 추가 시 도메인 단위(예: `router/orders`)로 응집도 있게 배치.

## 테스트 가이드라인

- 현재 자동 테스트가 제한적이므로 신규 기능에는 테스트 추가를 권장.
- 백엔드: `ecommerce/platform/backend/tests` 경로에 API/CRUD 단위 테스트 추가.
- 프론트엔드: 화면 로직 테스트는 `app/**/__tests__` 또는 `*.test.ts(x)` 패턴 사용.
- 최소 검증: 변경 후 `npm run lint` + 주요 API 수동 스모크 테스트(예: `/`, `/users/me`).

## 커밋 및 PR 가이드라인

- 최근 이력은 `이름_변경요약` 또는 `이름-주제설명` 형태가 많습니다(예: `준석_배송지UI안뜨게 수정`).
- 권장 커밋 형식: `영역: 변경 요약` (예: `use/usrs: 로그인 이력 metadata 저장 수정`).
- PR은 자동으로 진행하지 않습니다.

## 보안 및 설정 주의사항

- `.env`와 API 키는 커밋 금지, `.env.example`만 갱신.
- `docker-compose.yml`의 민감값은 로컬 개발용으로만 사용하고 배포 환경에서는 별도 시크릿 관리 사용.
