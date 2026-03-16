# Context-Aware Patch Generation Design

## Goal

원본 사이트 코드베이스를 직접 수정하지 않고, 로컬 코드 문맥을 분석해 `generated/<site>/<run-id>/` 아래에 실제 적용 가능한 patch proposal과 supporting generated files를 생성한다.

## Constraints

- `food`, `bilyeo`, `ecommerce`를 포함한 원본 사이트 디렉토리는 read-only로 취급한다.
- 모든 생성물은 `generated/` 또는 `runtime/` 아래에만 기록한다.
- validation/apply/export는 원본이 아니라 runtime copy 기준으로만 수행한다.
- 외부 정답이나 하드코딩된 사이트별 템플릿 의존을 줄이고, 로컬 코드 증거 기반으로 변경 계획을 만든다.

## Recommended Architecture

### 1. Read-Only Codebase Mapping

기존 `site_analyzer.py`의 capability 체크 수준을 넘어서, 다음을 수집하는 codebase mapper를 둔다.

- framework / router / entrypoint 위치
- auth 흐름 관련 함수, 모델, middleware, cookie/token usage
- API client / service / adapter / repository 계층 위치
- frontend mount point, state/store, shared layout 진입점
- 변경 후보 파일과 근거 line reference

산출물은 정규화된 JSON manifest로 저장한다.

### 2. Patch Planning Layer

LLM 또는 규칙 기반 planner는 mapper 결과만 입력으로 받아 다음을 만든다.

- target files
- why these files are chosen
- intended edits
- required new files
- risks / unknowns

이 단계에서는 아직 코드 본문을 쓰지 않는다. 목적은 “무엇을 어디에 왜 바꿀지”를 명시하는 것이다.

### 3. Patch Proposal Generation

generator는 원본 파일 내용을 읽어 다음 산출물을 만든다.

- unified diff patch
- patch에 포함되지 않는 supporting generated files
- patch intent / assumptions / unresolved items

핵심은 템플릿 파일을 곧바로 내보내는 것이 아니라, 실제 원본 파일의 문맥과 import 구조를 반영한 수정안을 만드는 것이다.

### 4. Runtime-Only Apply and Verification

patch proposal은 원본이 아니라 runtime workspace 복사본에만 적용한다.

- patch apply
- framework-aware smoke/build/test
- export patch and metadata

이 흐름은 기존 onboarding approval/export 구조와 호환된다.

## Initial Scope

첫 구현 범위는 전체 코드 생성기가 아니라 다음 두 가지다.

- 기존 템플릿 generator를 대체할 수 있는 `patch proposal artifact` 도입
- 실제 원본 파일을 수정 대상으로 삼되, 결과는 `generated/` patch로만 남기기

직접 원본 쓰기, 자동 원본 반영, 광범위한 framework 지원은 초기 범위에서 제외한다.

## Why This Direction

- 원본 보존 원칙을 유지한다.
- data leakage 없이 로컬 코드 증거만으로 생성한다.
- 사람 검토와 Slack approval 흐름에 자연스럽게 맞는다.
- 템플릿 기반 prototype에서 실전형 patch generation으로 확장 가능한 중간 단계다.

## Risks

- line-based diff 생성은 문맥 선택이 나쁘면 brittle할 수 있다.
- framework별 conventions를 충분히 읽지 못하면 low-quality patch가 생성될 수 있다.
- patch planning without execution feedback can still overfit to shallow signals.

## Follow-Up

다음 구현 단계는 `context-aware patch proposal`을 생성하는 mapper/planner/generator 파이프라인을 추가하고, 기존 overlay/template 흐름을 점진적으로 대체하는 것이다.
