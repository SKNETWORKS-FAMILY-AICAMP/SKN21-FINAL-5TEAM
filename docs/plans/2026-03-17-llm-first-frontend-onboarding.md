# LLM-First Frontend Onboarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** onboarding 파이프라인이 frontend에 대해 실제 widget file과 mount patch를 생성하고, 그 source provenance를 `llm`, `recovered_llm`, `hard_fallback` 중 하나로 기록하도록 만든다.

**Architecture:** `codebase_mapper`는 후보와 힌트만 수집하고, LLM interpreter/generator가 target file, widget path, import/mount strategy, artifact 내용을 제안한다. deterministic layer는 schema/path/patch validation과 materialization, recovery routing, hard fallback만 담당한다.

**Tech Stack:** Python, pytest, onboarding orchestrator, codebase mapper, role runner, patch planner, template generator, frontend evaluator

---

### Task 1: Lock the frontend artifact contract in tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_template_generator.py`
- Modify: `chatbot/tests/onboarding/test_frontend_mount_generator.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`

**Step 1: Write the failing tests**

아래 기대를 먼저 테스트로 고정한다.
- frontend generation result에 widget file artifact가 포함된다.
- mount patch는 기존처럼 생성되되 widget file path와 일관된다.
- orchestrator/materialization 단계가 frontend file + patch 둘 다 반영한다.

**Step 2: Run tests to verify they fail**

Run:
- `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k frontend -v`
- `uv run pytest chatbot/tests/onboarding/test_frontend_mount_generator.py -v`
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k frontend -v`

Expected: FAIL

**Step 3: Write minimal implementation expectations**

fixture와 assertion을 최소 단위로 추가해 artifact shape을 명확히 한다.

**Step 4: Run tests again**

Run the same commands; expected: still FAIL but now on missing implementation, not bad test setup

### Task 2: Split frontend generator responsibility out of template_generator

**Files:**
- Modify: `chatbot/src/onboarding/template_generator.py`
- Create: `chatbot/src/onboarding/frontend_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`

**Step 1: Write the failing test**

`generate_frontend_widget_artifact()` 또는 동등한 API가 run root를 받아 widget file path를 반환하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k widget -v`
Expected: FAIL

**Step 3: Write minimal implementation**

`template_generator.py`에서 frontend 관련 책임을 분리하고, 실제 widget file artifact writer를 새 모듈로 도입한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k widget -v`
Expected: PASS

### Task 3: Add LLM-first frontend interpretation output

**Files:**
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Test: `chatbot/tests/onboarding/test_codebase_mapper.py`
- Test: `chatbot/tests/onboarding/test_patch_planner.py`

**Step 1: Write failing tests**

아래를 테스트로 고정한다.
- frontend interpreter payload가 `target_file`, `widget_file_path`, `mount_strategy`를 포함한다.
- invalid path proposal은 validator/recovery로 넘길 수 있는 shape로 정규화된다.

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k frontend -v`
- `uv run pytest chatbot/tests/onboarding/test_patch_planner.py -k frontend -v`

Expected: FAIL

**Step 3: Implement**

frontend 전용 interpretation schema와 proposal builder를 추가한다. 여기서는 deterministic selection을 늘리지 말고 LLM output contract만 강화한다.

**Step 4: Verify**

Run the same commands; expected: PASS

### Task 4: Generate widget artifact and mount patch from LLM proposal

**Files:**
- Modify: `chatbot/src/onboarding/frontend_generator.py`
- Modify: `chatbot/src/onboarding/template_generator.py`
- Test: `chatbot/tests/onboarding/test_template_generator.py`
- Test: `chatbot/tests/onboarding/test_frontend_mount_generator.py`

**Step 1: Write failing tests**

- LLM proposal을 입력받아 widget file artifact를 생성하는 테스트
- 같은 proposal에서 mount patch를 생성하는 테스트
- widget 경로와 patch import 경로가 일치하는 테스트

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_template_generator.py -k llm_frontend -v`
- `uv run pytest chatbot/tests/onboarding/test_frontend_mount_generator.py -k llm_frontend -v`

Expected: FAIL

**Step 3: Implement**

proposal-driven artifact generator를 추가한다. deterministic default path 선택은 금지하고, proposal이 없거나 invalid하면 recovery/hard fallback 경로로 넘긴다.

**Step 4: Verify**

Run the same commands; expected: PASS

### Task 5: Add frontend validator and recovery routing

**Files:**
- Modify: `chatbot/src/onboarding/frontend_evaluator.py`
- Create: `chatbot/src/onboarding/frontend_recovery.py`
- Test: `chatbot/tests/onboarding/test_frontend_evaluator.py`
- Test: `chatbot/tests/onboarding/test_patch_apply.py`

**Step 1: Write failing tests**

- invalid target file path는 validation failure가 나는 테스트
- malformed import/mount patch는 recovery input으로 전환되는 테스트
- recovery 성공 시 `source == "recovered_llm"`
- recovery 실패 시 `source == "hard_fallback"`

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_frontend_evaluator.py -k recovery -v`
- `uv run pytest chatbot/tests/onboarding/test_patch_apply.py -k frontend -v`

Expected: FAIL

**Step 3: Implement**

frontend validation contract와 recovery adapter를 추가한다. recovery는 path normalization, import 위치 보정, trivial patch formatting 복구까지만 허용한다.

**Step 4: Verify**

Run the same commands; expected: PASS

### Task 6: Integrate frontend source selection into orchestrator

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/exporter.py`
- Test: `chatbot/tests/onboarding/test_orchestrator.py`
- Test: `chatbot/tests/onboarding/test_exporter.py`

**Step 1: Write failing tests**

- orchestrator가 `llm`, `recovered_llm`, `hard_fallback` 중 최종 frontend source를 기록하는 테스트
- export 결과에 widget file artifact와 mount patch가 함께 포함되는 테스트

**Step 2: Run tests**

Run:
- `uv run pytest chatbot/tests/onboarding/test_orchestrator.py -k frontend_source -v`
- `uv run pytest chatbot/tests/onboarding/test_exporter.py -k frontend -v`

Expected: FAIL

**Step 3: Implement**

frontend artifact lifecycle을 orchestrator에 연결하고, 최종 source 선택과 export metadata를 추가한다.

**Step 4: Verify**

Run the same commands; expected: PASS

### Task 7: Verify touched suites

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_template_generator.py chatbot/tests/onboarding/test_frontend_mount_generator.py chatbot/tests/onboarding/test_codebase_mapper.py chatbot/tests/onboarding/test_patch_planner.py chatbot/tests/onboarding/test_frontend_evaluator.py chatbot/tests/onboarding/test_patch_apply.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_exporter.py -q`

Expected: PASS
