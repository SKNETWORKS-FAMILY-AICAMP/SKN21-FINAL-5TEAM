# Onboarding Debug Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실행 추적, LLM 단계별 debug 로그, 파일 기준 활동 인덱스를 추가한다.

**Architecture:** 공용 logging helper를 두고 orchestrator/role runner/codebase interpreter/patch proposal writer가 동일한 포맷으로 report root에 로그를 남긴다.

**Tech Stack:** Python, json/jsonl, pytest

---

### Task 1: Failing tests for trace/debug/file activity

**Files:**
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`
- Modify: `chatbot/tests/onboarding/test_llm_role_runner.py`

**Step 1:** execution trace 생성 테스트
**Step 2:** llm debug artifact 생성 테스트
**Step 3:** file activity 생성 테스트
**Step 4:** focused pytest로 RED 확인

### Task 2: Minimal logging helpers

**Files:**
- Create: `chatbot/src/onboarding/debug_logging.py`

**Step 1:** append trace helper
**Step 2:** write llm debug helper
**Step 3:** update file activity helper

### Task 3: Wire into orchestrator and LLM steps

**Files:**
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/src/onboarding/role_runner.py`
- Modify: `chatbot/src/onboarding/codebase_mapper.py`
- Modify: `chatbot/src/onboarding/patch_planner.py`

**Step 1:** key stage trace logging
**Step 2:** LLM failure/success debug logging
**Step 3:** target file activity logging

### Task 4: Summary/report surfacing

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1:** summary에 debug artifact 경로 노출

### Task 5: Full verification

**Step 1:** onboarding pytest 전체
**Step 2:** py_compile
