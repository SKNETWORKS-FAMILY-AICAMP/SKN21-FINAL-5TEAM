# Generator Confidence And Patch Prompt Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `Generator` role이 `"0.82 (중간-높음)"` 같은 confidence 문자열에도 fallback하지 않도록 정규화를 추가하고, LLM patch draft 프롬프트를 더 엄격하게 만들어 malformed unified diff 확률을 낮춘다.

**Architecture:** `role_runner.py`에서 confidence 필드를 느슨하게 숫자 추출 방식으로 정규화하고, `patch_planner.py`의 patch system prompt에 hunk header 형식과 파일별 full diff structure를 더 강하게 요구한다.

**Tech Stack:** Python, pytest, regex, onboarding role runner, patch planner

---

### Task 1: Add failing test for confidence string normalization

**Files:**
- Modify: `chatbot/tests/onboarding/test_llm_role_runner.py`
- Modify: `chatbot/src/onboarding/role_runner.py`

**Step 1: Write the failing test**

`confidence: "0.82 (중간-높음)"` 같은 payload가 `Generator` role에서 fallback 없이 파싱되는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k confidence_string -v`
Expected: FAIL because current parser calls `float()` directly

**Step 3: Write minimal implementation**

정규식으로 첫 번째 숫자 토큰을 추출해 confidence float로 변환한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py -k confidence_string -v`
Expected: PASS

### Task 2: Strengthen patch draft prompt contract

**Files:**
- Modify: `chatbot/tests/onboarding/test_llm_patch_draft.py`
- Modify: `chatbot/src/onboarding/patch_planner.py`

**Step 1: Write the failing test**

patch system prompt에:
- valid hunk header example
- every target file needs full `---/+++/@@` structure
- no prose/comments outside diff

가 명시되는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k prompt_contract -v`
Expected: FAIL because current prompt is too generic

**Step 3: Write minimal implementation**

system prompt를 강화하되 기존 valid test를 깨지 않는 선에서만 수정한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_llm_patch_draft.py -k prompt_contract -v`
Expected: PASS

### Task 3: Verify touched suites

**Step 1: Run**

`uv run pytest chatbot/tests/onboarding/test_llm_role_runner.py chatbot/tests/onboarding/test_llm_patch_draft.py -v`

Expected: PASS
