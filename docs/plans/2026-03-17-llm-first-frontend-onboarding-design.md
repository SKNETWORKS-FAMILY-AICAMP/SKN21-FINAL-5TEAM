# LLM-First Frontend Onboarding Design

## Goal
어떤 프론트엔드 구조의 웹사이트가 들어와도 온보딩 시스템이 LLM을 중심으로 `widget file 생성`과 `mount patch 생성`을 수행할 수 있게 만든다. deterministic 로직은 후보 수집, 안전 검증, artifact materialization, hard fallback에만 남긴다.

## Problem
현재 프론트엔드 온보딩은 mount patch 초안만 만드는 수준이다. 실제 `SharedChatbotWidget` 파일 생성이 없고, 설치 전략 결정도 framework/entry/mount 위치를 깊게 해석하지 못한다. 결과적으로 "실제 설치"가 아니라 "삽입 초안"에 가깝다.

## Product Direction
- 사이트별 프론트 구조를 사전에 고정된 규칙으로 가정하지 않는다.
- LLM이 코드베이스를 읽고 설치 전략을 제안한다.
- deterministic은 "무엇을 할지"가 아니라 "제안이 안전하게 실행 가능한지"만 판정한다.
- LLM proposal이 실패하면 recovery agent가 수정 시도하고, 그것도 실패하면 hard fallback으로 내려간다.

## Scope For This Milestone
- 실제 frontend widget source file 생성
- 실제 mount patch 생성
- orchestrator가 두 artifact를 run bundle에 materialize

이번 마일스톤에서는 build/run 검증은 포함하지 않는다.

## Architecture

### 1. Observability Layer
`codebase_mapper`는 결정하지 않고 관측만 수행한다.

출력:
- framework signals
- frontend entry 후보
- layout/root/app/router 후보
- 기존 chatbot 관련 컴포넌트/경로 후보

### 2. LLM Frontend Interpreter
LLM이 codebase map과 핵심 파일 스니펫을 읽고 설치 전략을 제안한다.

출력:
- `target_file`
- `widget_file_path`
- `import_strategy`
- `mount_strategy`
- `insertion_anchors`
- `rejected_alternatives`
- `confidence`

이 단계는 구조 해석 책임만 가진다. 실제 파일 텍스트는 생성하지 않는다.

### 3. LLM Frontend Artifact Generator
LLM이 interpreter proposal을 입력으로 받아 실제 artifact를 생성한다.

출력:
- `files/frontend/.../SharedChatbotWidget.*`
- `patches/frontend_widget_mount.patch`
- proposal/report artifact

### 4. Validator
deterministic validator는 아래만 검사한다.

- 제안 경로가 workspace 내부인지
- target file이 실제 존재하는지
- patch가 apply 가능한지
- obvious duplicate import가 아닌지
- artifact schema가 맞는지

validator는 설치 전략을 재결정하지 않는다.

### 5. Recovery Agent
validator나 schema validation이 실패하면 recovery agent가 실패 이유를 받아 delta 수정안을 생성한다.

입력:
- original proposal
- validation error
- rejected patch
- code context

출력:
- recovered proposal/artifact
- recovery notes

### 6. Hard Fallback
recovery도 실패하면 deterministic hard fallback을 사용한다.

hard fallback은 성공한 설치를 가장하지 않는다. 대신 아래를 남긴다.
- 안전한 placeholder widget artifact 또는 empty frontend artifact
- mount 미적용 상태
- human review required report
- source=`hard_fallback`

## Provenance Model
frontend artifact source는 반드시 아래 셋 중 하나다.

- `llm`
- `recovered_llm`
- `hard_fallback`

orchestrator는 최종 export 시 어떤 source가 채택됐는지 기록해야 한다.

## Agent Topology

### Controller
소유 파일:
- `chatbot/src/onboarding/orchestrator.py`
- `chatbot/src/onboarding/runtime_runner.py`
- `chatbot/src/onboarding/exporter.py`

책임:
- 단계 오케스트레이션
- candidate source 선택
- recovery/hard fallback 전이
- 최종 materialization/export

### Interpreter / Prompt Agent
소유 파일:
- `chatbot/src/onboarding/codebase_mapper.py`
- `chatbot/src/onboarding/patch_planner.py`
- `chatbot/src/onboarding/role_runner.py`

책임:
- frontend installation proposal schema
- interpreter prompt
- generator prompt contract

### Frontend Artifact Agent
소유 파일:
- `chatbot/src/onboarding/template_generator.py`
- 필요 시 새 frontend generator module

책임:
- widget source artifact 생성
- mount patch artifact 생성

### Validation / Recovery Agent
소유 파일:
- `chatbot/src/onboarding/frontend_evaluator.py`
- 필요 시 새 recovery module

책임:
- artifact validation
- recovery input/output contract
- recovery decision support

## Why This Split
- `orchestrator`는 최종 통합 지점이라 단일 owner가 필요하다.
- generator와 validator를 분리해야 LLM output을 독립적으로 판정할 수 있다.
- recovery를 generator 내부에 넣으면 실패 원인과 수정 시도가 섞여 provenance가 흐려진다.

## Milestone Success Criteria
- run bundle에 실제 frontend widget file이 생성된다.
- run bundle에 실제 mount patch가 생성된다.
- orchestrator가 frontend artifact source를 `llm`, `recovered_llm`, `hard_fallback` 중 하나로 기록한다.
- 실패 시 hard fallback이 "설치 성공"처럼 보이지 않고 명확한 review signal을 남긴다.

## Non-Goals
- frontend build 검증
- runtime mount 실행 검증
- backend auth/order/product adapter 완성
- self-healing infinite edit loop
