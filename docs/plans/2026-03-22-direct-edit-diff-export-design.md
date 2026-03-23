# Direct Edit + Diff Export Onboarding Design

## Goal
온보딩 생성 파이프라인을 `patch-first`에서 `runtime direct-edit + final diff export` 구조로 전환한다. 생성과 repair는 runtime workspace 파일을 직접 수정하고, 사람 검토와 재현성 검증에 필요한 patch는 마지막 export 단계에서만 만든다.

## Problem
현재 구조는 planning, generation, repair, validation, export가 모두 patch artifact를 중심으로 엮여 있다.

- LLM이 무엇을 고칠지 맞춰도 unified diff 문법을 틀리면 전체 생성이 실패한다.
- `food-run-051`처럼 runtime validation 실패와 patch apply 실패가 같은 실패 집합으로 섞여 보인다.
- `proposed.patch`, `llm-proposed.patch`, runtime repair patch가 모두 “수정 수단”과 “최종 산출물” 역할을 동시에 가져서 상태 분리가 흐려진다.
- 이미 존재하는 [`export_runtime_patch`](/Users/junseok/Projects/SKN21-FINAL-5TEAM/chatbot/src/onboarding/exporter.py)는 좋은 export primitive인데, 앞단 전체가 아직 patch string 생산에 과하게 묶여 있다.

## Core Decision
최종 구조는 아래 순서로 고정한다.

1. `source_root`는 읽기 전용 기준본이다.
2. `runtime/<site>/<run_id>/workspace/`는 유일한 편집 대상이다.
3. planning 단계는 “어떤 파일을 왜 고칠지”를 JSON artifact로 기록한다.
4. generation 단계는 patch text 대신 direct edit payload를 만들고 runtime workspace에 적용한다.
5. repair 단계도 patch text 대신 direct edit payload를 만들어 같은 runtime workspace에 적용한다.
6. validation은 수정된 runtime workspace를 기준으로 실행한다.
7. export 단계에서만 `source_root`와 runtime workspace diff를 `approved.patch`로 기록한다.
8. replay validation은 export된 patch를 clean workspace에 다시 적용해 재현성을 검증한다.

즉, patch는 더 이상 “작업 도중의 실행 수단”이 아니라 “검토와 promotion을 위한 최종 결과물”이다.

## Architecture

### Source of Truth
- 기준본: `source_root`
- 작업본: `runtime_workspace`
- 최종 산출물: `reports/approved.patch`

`generated/<site>/<run_id>/patches/`는 static template patch와 호환성 artifact를 위해 잠시 유지할 수 있지만, LLM draft와 runtime repair의 기본 실행 경로에서는 빠진다.

### New Runtime Editing Layer
새 공통 편집 계층을 추가한다.

- 입력:
  - file path
  - operation type
  - insertion hint or replacement block
  - provenance
- 동작:
  - target path validation
  - UTF-8 text read/write
  - exact replace / append / structured insert
  - applied edit summary 반환

이 계층은 generation과 repair가 같이 쓴다.

### Planning Artifacts
기존 `patch-proposal.json`은 유지하되 의미를 좁힌다.

- 유지:
  - target files
  - reasons
  - recommended outputs
- 변경:
  - “patch proposal”이 아니라 “edit target proposal”로 해석

추가 artifact:

- `reports/edit-plan.json`
  - target files
  - intended operations
  - generated file dependencies
  - provenance
- `reports/edit-execution.json`
  - applied edits
  - skipped edits
  - target validation failures
  - source (`deterministic`, `llm`, `recovered_llm`, `hard_fallback`)

### Runtime Repair
`runtime_llm_repair.py`는 unified diff를 반환받아 `git apply`/`patch`로 붙이던 구조에서 벗어난다.

- 새 prompt는 patch가 아니라 edit payload를 반환한다.
- guardrail은 patch target extraction 대신 file path allowlist와 operation validation으로 처리한다.
- repair 결과는 `reports/runtime-repair-<attempt>.json` 또는 기존 debug artifact 안의 `applied_edits`로 남긴다.

### Export and Replay
`export_runtime_patch()`는 중심 export primitive로 승격한다.

- runtime workspace와 source_root diff를 `approved.patch`로 생성
- changed_files, strategy_provenance, recovery_provenance 외에 아래를 기록
  - `edit_artifacts`
  - `replay_report_path`
  - `replay_passed`

새 replay 단계:

1. clean workspace 준비
2. `approved.patch` 적용
3. build/smoke/frontend/backend evaluation 재실행
4. 결과를 `reports/export-replay-validation.json`에 기록

## Data Model

### Manifest
`OverlayManifest`는 backward compatible하게 확장한다.

- 유지:
  - `generated_files`
  - `patch_targets`
- 추가:
  - `edit_artifacts`
  - `export_artifacts`

의도:
- legacy static patch는 `patch_targets`로 계속 처리 가능
- direct-edit generation 결과는 `edit_artifacts`로 분리

### Report Set
최종 보고서는 아래처럼 역할이 분리된다.

- `patch-proposal.json`: 수정 후보 선정
- `edit-plan.json`: planned edit operations
- `edit-execution.json`: generation edits 적용 결과
- `merge-simulation.json`: generated files + static patch 적용 결과
- `runtime-validation.json` 또는 기존 validation reports: 실제 runtime 검증 결과
- `export-metadata.json`: export patch 메타데이터
- `export-replay-validation.json`: exported patch clean replay 결과

### Failure Taxonomy
patch format 오류를 중심으로 보던 기존 분류를 아래처럼 바꾼다.

- `edit_payload_invalid`
- `edit_target_rejected`
- `edit_apply_failed`
- `runtime_validation_failed`
- `export_diff_failed`
- `replay_apply_failed`
- `replay_validation_failed`

`invalid_patch_format`, `invalid_patch_targets`, `corrupt_patch`는 legacy compatibility reason으로만 남긴다.

## Flow

### Planning
1. analysis 결과와 codebase map으로 edit target 선정
2. `patch-proposal.json` 기록
3. deterministic/LLM generator가 `edit-plan.json` 생성

### Generation
1. runtime workspace 준비
2. scaffold/generated files 복사
3. deterministic edits 적용
4. optional LLM edits 적용
5. `edit-execution.json` 기록

### Validation
1. runtime workspace 기준 frontend/backend/bootstrap/smoke 실행
2. 실패 시 runtime repair가 같은 runtime workspace를 직접 수정
3. retry 수행

### Export
1. `export_runtime_patch()`로 `approved.patch` 생성
2. clean replay workspace에 patch 재적용
3. replay validation 실행
4. 승인 가능한 결과만 export metadata에 `replay_passed: true` 기록

## Compatibility Rules
- `approved.patch`와 `export-metadata.json` 계약은 유지한다.
- `generate_llm_patch_draft` 플래그와 `llm-proposed.patch` 산출물은 한 릴리스 동안 deprecated alias로 유지할 수 있다.
- Slack/CLI/result payload는 기존 키를 유지하되, 새 키를 병행 추가한다.
- `patch-comparison.json`은 “deterministic direct edit export” 대 “llm direct edit export” 비교로 의미를 바꾼다.

## Success Criteria
- generation과 repair가 unified diff 문법에 의존하지 않고 runtime workspace를 직접 수정한다.
- validation 실패와 patch apply 실패가 별도 failure code로 분리된다.
- `approved.patch`는 export 시점에만 생성되고, clean replay에 다시 적용 가능하다.
- `food-run-051` 유형 실패에서 “LLM patch corrupt” 대신 “edit applied but validation failed” 또는 “replay failed”처럼 실제 실패 위치가 보인다.

## Risks
- direct edit payload가 너무 자유로우면 unsafe write가 될 수 있다.
- runtime workspace와 source_root diff가 예상보다 커질 수 있다.
- 기존 테스트가 `llm-proposed.patch` 존재를 강하게 기대하고 있어 전환 비용이 크다.

완화:
- allowlist target validation 유지
- 공통 file edit helper에서 exact path / UTF-8 / no parent traversal 검사 강제
- 기존 artifact 이름은 compatibility layer로 한동안 유지
- replay validation을 export gate로 삼아 재현성 없는 결과를 차단

## Recommendation
전환 순서는 아래가 맞다.

1. direct edit schema와 apply helper 추가
2. patch planner를 edit planner로 확장
3. orchestrator generation/validation/export 재배선
4. runtime repair를 same helper 위로 이동
5. replay validation과 report schema 정리

이 순서면 기존 `export_runtime_patch()` 자산을 살리면서, `food-run-051`에서 드러난 patch-format 병목을 가장 직접적으로 제거할 수 있다.
