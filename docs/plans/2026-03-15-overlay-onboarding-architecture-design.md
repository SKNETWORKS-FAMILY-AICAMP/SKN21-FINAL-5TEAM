# Overlay-Based SaaS Onboarding Architecture Design

## Goal

원본 웹사이트 코드를 직접 수정하지 않고, 에이전트가 분석 결과를 바탕으로 `overlay bundle`을 생성하고, 임시 runtime 복사본에서 검증한 뒤, 최종적으로 patch 또는 PR 형태로 반영하는 SaaS 온보딩 구조를 정의한다.

## Why

현재 `ecommerce`, `food`, `bilyeo`는 "SaaS 도입 전 원본 사이트" 역할도 겸한다. 이 원본을 직접 수정하면 다음 문제가 생긴다.

- 도입 전 상태를 기준 데이터로 유지할 수 없다.
- 에이전트 품질 평가가 왜곡된다.
- 실패한 자동 생성 결과가 원본에 오염된다.
- 실전 반영과 개발 실험의 경계가 사라진다.

따라서 에이전트는 원본을 수정하는 대신, 원본에 적용 가능한 결과물을 생성해야 한다.

## Core Decision

최종 구조는 아래 순서로 고정한다.

1. 원본 사이트는 읽기 전용으로 유지
2. 에이전트는 `overlay bundle` 생성
3. runner가 원본 복사본에 overlay 적용
4. docker / smoke test는 runtime 복사본에서만 실행
5. 승인된 결과만 patch 또는 PR로 변환

즉, 에이전트의 역할은 "원본 수정"이 아니라 "반영 가능한 수정안 생성"이다.

## Directory Model

실제 저장 구조는 아래를 권장한다.

```text
generated/
  <site>/
    <run_id>/
      manifest.json
      files/
      patches/
      smoke-tests/
      reports/

runtime/
  <site>/
    <run_id>/
      workspace/
      logs/
      artifacts/
```

원본 사이트 디렉터리는 그대로 유지한다.

```text
ecommerce/
food/
bilyeo/
chatbot/
docker/
```

초기 단계에서는 현재 루트의 `ecommerce`, `food`, `bilyeo`를 원본으로 간주하고, `generated/`, `runtime/`만 새로 추가하면 된다.

## Overlay Bundle

overlay bundle은 한 번의 온보딩 시도 결과물이다.

구성:

- `manifest.json`: 생성물 메타데이터
- `files/`: 새로 추가할 파일
- `patches/`: 기존 파일 수정 patch
- `smoke-tests/`: 검증 스크립트
- `reports/`: 분석 및 실행 결과

이 번들 하나만으로 아래를 알 수 있어야 한다.

- 어떤 원본 사이트를 분석했는지
- 무엇을 생성했는지
- 어떤 파일을 수정하려는지
- 어떤 테스트를 돌릴 것인지
- 검증 결과가 어땠는지

## Manifest Schema

`manifest.json`은 최소 아래 필드를 포함한다.

- `run_id`
- `site`
- `source_root`
- `created_at`
- `agent_version`
- `analysis`
- `generated_files`
- `patch_targets`
- `docker`
- `tests`
- `status`

예시:

```json
{
  "run_id": "food-20260315-001",
  "site": "food",
  "source_root": "/workspace/food",
  "created_at": "2026-03-15T12:00:00+09:00",
  "agent_version": "v1",
  "analysis": {
    "auth": {
      "type": "session_cookie",
      "login_entrypoints": ["users/views.py:login"],
      "me_entrypoints": ["users/views.py:me"]
    },
    "product_api": ["/api/products/"],
    "order_api": ["/api/orders/"],
    "frontend_mount_points": ["src/App.js"]
  },
  "generated_files": [
    "files/backend/chat_auth.py",
    "files/frontend/chatbot/Widget.tsx"
  ],
  "patch_targets": [
    "patches/users_views.patch",
    "patches/app_mount.patch"
  ],
  "docker": {
    "compose_override": "files/docker-compose.override.yml"
  },
  "tests": {
    "smoke": [
      "smoke-tests/login.sh",
      "smoke-tests/chat_auth_token.sh"
    ]
  },
  "status": "generated"
}
```

## Run Lifecycle

`run_id`는 하나의 실험 단위다.

흐름:

1. run 생성
2. 원본 분석
3. overlay bundle 생성
4. runtime 복사본 생성
5. overlay 적용
6. docker 실행
7. smoke test 실행
8. 결과 리포트 저장
9. `approved` 또는 `rejected`

여러 run이 생길 수 있지만, 모든 run을 합치는 것이 기본 전략은 아니다. 보통은 승인된 한 개의 run을 채택한다. 여러 run을 섞어야 하면 별도의 release-candidate run을 다시 만든다.

## Runtime Apply Flow

runner는 아래 순서로 동작한다.

1. 원본 사이트를 `runtime/<site>/<run_id>/workspace/`로 복사
2. `files/`를 복사
3. `patches/`를 적용
4. 필요한 env / compose override 생성
5. docker로 실행
6. smoke test 수행
7. 로그 및 artifacts 저장

모든 테스트는 runtime 복사본에서만 수행한다.

## Final Integration

승인된 run은 직접 원본에 쓰지 않는다.

최종 반영은 둘 중 하나로 수행한다.

- clean worktree에 overlay 적용 후 git commit 생성
- runtime workspace 기준 git diff를 뽑아 patch 또는 PR 브랜치 생성

권장안은 `git patch / PR 생성`이다.

이 방식의 장점:

- 사람이 diff를 검토할 수 있다.
- staging 검증과 운영 반영을 분리할 수 있다.
- rollback이 쉽다.
- 실전에서도 안전하다.

## Agent Responsibility

MVP V1에서 에이전트는 아래까지만 책임진다.

- 로그인 구조 탐지
- 상품/주문 API 탐지
- 챗봇 삽입 위치 탐지
- overlay bundle 생성
- smoke test 스크립트 생성

최종 merge는 사람이 승인한 뒤에만 이루어진다.

## Testing Strategy

테스트는 세 단계로 나눈다.

1. 분석 테스트
   - 원본 사이트에서 auth/product/order/frontend mount를 정확히 탐지하는지

2. overlay 적용 테스트
   - runtime 복사본에 `files/`와 `patches/`가 정상 적용되는지

3. smoke test
   - 로그인
   - `/api/chat/auth-token`
   - 챗봇 stream 시작
   - 상품 조회
   - 주문 조회

## Non-Goals

이번 구조 설계의 범위에는 아래를 포함하지 않는다.

- FAQ/RAG 자동 인덱싱
- 이미지 벡터화
- 완전 자동 merge
- 운영 배포 자동 승인
