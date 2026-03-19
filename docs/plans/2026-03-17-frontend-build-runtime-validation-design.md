# Frontend Build Runtime Validation Design

## Goal
LLM-first frontend onboarding 결과에 대해 runtime workspace 안에서 실제 frontend build를 수행하고, lightweight runtime validation까지 남겨 "widget file 생성 + mount patch 생성"이 실제 앱 수준에서 최소한 깨지지 않는지 검증한다.

## Problem
현재 frontend onboarding은 artifact 생성과 mount patch materialization까지만 검증한다. 즉, `SharedChatbotWidget` 파일과 patch가 생성돼도:

- package manager가 실제로 의존성을 설치할 수 있는지
- build command가 통과하는지
- import path가 빌드 관점에서 유효한지
- mount target이 실제 앱 엔트리와 일치하는지

를 확인하지 않는다. 결과적으로 "artifact는 생겼지만 실제 앱에서는 깨지는" 상태를 놓칠 수 있다.

## Recommended Approach
`Build + static runtime smoke`를 도입한다.

- runtime workspace에서 frontend build를 실제 실행한다.
- 브라우저/E2E는 아직 하지 않는다.
- build 성공 후 정적 runtime checks를 실행한다.
- build plan 선택은 LLM-first로 두되, deterministic runner가 실행/수집/판정한다.
- build 실패 시 recovery agent가 대체 build plan 또는 lightweight fix proposal을 시도하고, 그래도 실패하면 `hard_fallback`으로 기록한다.

## Why Not Full Browser Runtime
Playwright/browser-based runtime은 사이트별 편차가 크고 dev server orchestration이 무겁다. 지금 목표는 "범용 onboarding 시스템의 첫 실제 검증 계층"이므로, build와 정적 runtime check만으로도 실패의 큰 비율을 잡을 수 있다.

## Validation Contract

### Input
- `run_root`
- `runtime_workspace`
- `frontend framework hints`
- `package manager hints`
- `frontend artifact provenance`

### Output
- `framework`
- `package_manager`
- `build_attempted`
- `build_command`
- `build_passed`
- `install_attempted`
- `install_command`
- `runtime_checks`
- `source`
- `failure_reason`
- `recovery_notes`

## Responsibilities

### LLM
- 가장 적절한 build command 제안
- framework별 runtime check 전략 제안
- build failure 로그 기반 recovery command 또는 config-fix proposal 제안

### Deterministic
- package manager 후보 탐색
- install/build 실행
- stdout/stderr/exit code 수집
- timeout 관리
- output artifact 존재 확인
- import path / mount target / widget file 정적 검증
- recovery 결과 채택 여부 판정

## Runtime Checks

### Build check
- install command 수행 여부
- build command 수행 여부
- exit code
- output directory or framework artifact 존재

예시:
- React/Vite: `dist/`
- Next.js: `.next/`
- Vue/Vite: `dist/`

### Static runtime checks
- mount target file가 workspace에 존재하는지
- mount import path가 widget file과 일치하는지
- widget file이 실제 workspace에 복사되었는지
- build output이 존재할 때 target import path가 깨진 흔적이 없는지

## Recovery Model
build/runtime validation source는 다음 셋 중 하나다.

- `llm`
- `recovered_llm`
- `hard_fallback`

### Recovery can do
- build command 대체
- package manager command 대체
- trivial path normalization
- known framework artifact path 재평가

### Recovery must not do
- arbitrary source tree mutation
- silent dependency injection
- 브라우저/E2E 단계로 escalation

## Agent Topology

### Controller
소유 파일:
- `chatbot/src/onboarding/orchestrator.py`

책임:
- build/runtime validation stage 연결
- final source selection
- report/result wiring

### Build Plan Agent
소유 파일:
- `chatbot/src/onboarding/codebase_mapper.py`
- `chatbot/src/onboarding/patch_planner.py`
- 필요 시 새 build-plan helper

책임:
- frontend build/install command proposal
- framework/package manager hints 정리

### Validation Agent
소유 파일:
- `chatbot/src/onboarding/frontend_evaluator.py`
- `chatbot/src/onboarding/runtime_runner.py`
- 필요 시 새 `frontend_build_runner.py`

책임:
- install/build execution
- static runtime checks
- report artifact 작성

### Recovery Agent
소유 파일:
- `chatbot/src/onboarding/frontend_recovery.py`

책임:
- build/runtime failure 기반 recovery proposal
- `recovered_llm` vs `hard_fallback` 판정 지원

## Artifact Changes
- `reports/frontend-evaluation.json` 확장
- 새 `reports/frontend-build-validation.json` 추가 가능
- canonical/generation log에 build/install/runtime check 결과 기록

## Success Criteria
- runtime workspace에서 frontend install/build가 실제로 실행된다.
- build 결과와 failure reason이 artifact로 남는다.
- mount/widget/import 정적 runtime check가 함께 기록된다.
- recovery/hard fallback provenance가 frontend validation 결과에 포함된다.

## Non-Goals
- 브라우저 E2E
- visual regression
- 사이트별 dev server 부팅 자동화
- order/product/login 실통합 smoke
