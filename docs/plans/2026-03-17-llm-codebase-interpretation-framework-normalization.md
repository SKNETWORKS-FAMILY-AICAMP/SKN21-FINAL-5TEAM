# LLM Codebase Interpretation Framework Normalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `llm_codebase_interpretation`에서 `framework_assessment`가 문자열로 와도 fallback하지 않도록 최소 정규화를 추가한다.

**Architecture:** raw LLM JSON를 먼저 파싱한 뒤 `framework_assessment`만 dict로 normalize하고, 나머지 payload는 기존 schema validation과 candidate validation을 유지한다.

**Tech Stack:** Python, pydantic, pytest

---

### Task 1: Add failing test for string framework assessment

**Files:**
- Modify: `chatbot/tests/onboarding/test_codebase_mapper.py`
- Modify: `chatbot/src/onboarding/codebase_mapper.py`

**Step 1: Write the failing test**

문자열 `framework_assessment`를 반환하는 fake LLM 응답이 `source == "llm"`으로 저장되고, 결과 payload의 `framework_assessment`가 dict로 normalize되는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k framework_assessment -v`
Expected: FAIL because current validation requires a dict directly

**Step 3: Write minimal implementation**

`codebase_mapper.py`에서:
- raw JSON 파싱 helper 추가
- `framework_assessment`가 문자열이면 dict로 감싸는 normalization 추가
- 기존 ranked candidate validation 유지

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -k framework_assessment -v`
Expected: PASS

**Step 5: Verify nearby regressions**

Run: `uv run pytest chatbot/tests/onboarding/test_codebase_mapper.py -v`
Expected: PASS
