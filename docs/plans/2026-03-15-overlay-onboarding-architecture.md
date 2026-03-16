# Overlay-Based SaaS Onboarding Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 원본 사이트를 수정하지 않고, overlay bundle 생성과 runtime 복사본 검증을 통해 SaaS 온보딩을 평가할 수 있는 기본 도구를 구축한다.

**Architecture:** 에이전트는 원본을 읽고 `generated/<site>/<run_id>/`에 overlay bundle을 생성한다. runner는 원본을 `runtime/<site>/<run_id>/workspace/`로 복사한 뒤 bundle을 적용하고 docker / smoke test를 수행한다. 승인된 결과만 patch 또는 PR로 승격한다.

**Tech Stack:** Python, JSON schema-like manifest validation, Docker Compose, shell scripts, pytest

---

### Task 1: Create Overlay Manifest Model

**Files:**
- Create: `chatbot/src/onboarding/manifest.py`
- Create: `chatbot/tests/onboarding/test_manifest.py`

**Step 1: Write the failing test**

테스트 케이스:

- 유효한 manifest payload가 파싱되는지
- 필수 필드 누락 시 실패하는지
- `status`가 허용된 값만 받는지

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_manifest.py -v`
Expected: 모듈 없음 실패

**Step 3: Write minimal implementation**

- `OverlayManifest` 모델 작성
- `analysis`, `generated_files`, `patch_targets`, `docker`, `tests`, `status` 필드 정의
- 최소 validate 함수 제공

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_manifest.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/manifest.py chatbot/tests/onboarding/test_manifest.py
git commit -m "chatbot: add overlay manifest model"
```

### Task 2: Build Runtime Workspace Runner

**Files:**
- Create: `chatbot/src/onboarding/runtime_runner.py`
- Create: `chatbot/tests/onboarding/test_runtime_runner.py`

**Step 1: Write the failing test**

테스트 케이스:

- 원본 디렉터리를 runtime workspace로 복사하는지
- `files/`가 덮어써지는지
- patch 적용 대상 목록을 인식하는지

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_runtime_runner.py -v`
Expected: 모듈 없음 실패

**Step 3: Write minimal implementation**

- `prepare_runtime_workspace(source_root, generated_root, runtime_root)` 함수 작성
- 디렉터리 복사
- overlay files 복사
- patch 적용 전 단계까지 구현

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_runtime_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_runner.py chatbot/tests/onboarding/test_runtime_runner.py
git commit -m "chatbot: add runtime workspace runner"
```

### Task 3: Add Patch Apply Step

**Files:**
- Modify: `chatbot/src/onboarding/runtime_runner.py`
- Create: `chatbot/tests/onboarding/test_patch_apply.py`

**Step 1: Write the failing test**

테스트 케이스:

- unified diff patch가 runtime workspace에 적용되는지
- patch 실패 시 명확한 에러를 반환하는지

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_patch_apply.py -v`
Expected: patch apply 미구현 실패

**Step 3: Write minimal implementation**

- patch apply helper 구현
- manifest의 `patch_targets` 순서대로 적용
- 실패 시 어떤 patch에서 깨졌는지 반환

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_patch_apply.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/runtime_runner.py chatbot/tests/onboarding/test_patch_apply.py
git commit -m "chatbot: apply overlay patches in runtime runner"
```

### Task 4: Create Smoke Test Contract

**Files:**
- Create: `chatbot/src/onboarding/smoke_contract.py`
- Create: `docs/plans/2026-03-15-smoke-test-contract.md`

**Step 1: Write the failing test**

테스트 대신 계약 검증 항목 정의:

- 로그인 검증
- `/api/chat/auth-token`
- 챗봇 stream
- 상품 조회
- 주문 조회

**Step 2: Verify gap**

Run: `rg -n "chat/auth-token|smoke test|runtime workspace" docs chatbot/src`
Expected: 관련 계약 부족

**Step 3: Write minimal implementation**

- smoke step enum / config 구조 정의
- 문서에 기본 시나리오 기록

**Step 4: Verify output**

Run: `rg -n "chat/auth-token|smoke test|runtime workspace" docs chatbot/src`
Expected: 계약 문서와 코드 확인

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/smoke_contract.py docs/plans/2026-03-15-smoke-test-contract.md
git commit -m "docs: define onboarding smoke test contract"
```

### Task 5: Add Git Patch / PR Exporter

**Files:**
- Create: `chatbot/src/onboarding/exporter.py`
- Create: `chatbot/tests/onboarding/test_exporter.py`

**Step 1: Write the failing test**

테스트 케이스:

- runtime workspace와 원본 간 diff를 patch 파일로 내보내는지
- patch 경로가 `generated/<site>/<run_id>/reports/`에 저장되는지

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_exporter.py -v`
Expected: 모듈 없음 실패

**Step 3: Write minimal implementation**

- patch export 함수 구현
- 후속 PR 생성에 필요한 metadata 파일 작성

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_exporter.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/exporter.py chatbot/tests/onboarding/test_exporter.py
git commit -m "chatbot: export approved overlay as git patch"
```

### Task 6: Wire a Minimal CLI Runner

**Files:**
- Create: `chatbot/scripts/run_onboarding_overlay.py`
- Modify: `README.md`

**Step 1: Write the failing test**

테스트 또는 manual contract:

- `--site`, `--run-id`, `--source-root`, `--generated-root`, `--runtime-root` 입력을 받는지
- runtime 준비부터 export까지 단계별 로그를 출력하는지

**Step 2: Run verification to confirm it fails**

Run: `uv run python chatbot/scripts/run_onboarding_overlay.py --help`
Expected: 파일 없음 실패

**Step 3: Write minimal implementation**

- manifest load
- runtime workspace prepare
- patch apply
- smoke contract print 또는 실행 entrypoint
- patch export

**Step 4: Run verification**

Run: `uv run python chatbot/scripts/run_onboarding_overlay.py --help`
Expected: usage 출력

**Step 5: Commit**

```bash
git add chatbot/scripts/run_onboarding_overlay.py README.md
git commit -m "chatbot: add overlay onboarding runner cli"
```

### Task 7: Verify End-to-End on Sample Run

**Files:**
- No permanent code files required

**Step 1: Prepare a tiny sample overlay**

- 테스트용 fixture source
- `generated/test-site/run-001/` 예시 구성

**Step 2: Execute runner**

Run: `uv run python chatbot/scripts/run_onboarding_overlay.py --site test-site --run-id run-001 ...`

**Step 3: Verify output**

- runtime workspace 생성
- overlay 적용
- patch export
- report 생성

**Step 4: Commit**

```bash
git add -A
git commit -m "chatbot: verify overlay onboarding workflow"
```
