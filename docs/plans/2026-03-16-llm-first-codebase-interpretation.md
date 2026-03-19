# LLM-First Codebase Interpretation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** LLM이 codebase 구조를 해석한 artifact를 생성하고 patch planning이 이를 우선 사용하게 만든다.

**Architecture:** deterministic `codebase-map.json`은 raw scanner로 유지하고, 별도 LLM interpretation artifact를 생성한다. patch planner는 이 artifact의 ranked candidates를 우선 사용하고 실패 시 기존 deterministic selection으로 fallback한다.

**Tech Stack:** Python, pydantic, pytest

---

### Task 1: Interpretation runner tests

**Files:**
- Modify: `chatbot/tests/onboarding/test_codebase_mapper.py`

**Step 1:** LLM interpretation success test 작성
**Step 2:** invalid payload fallback test 작성
**Step 3:** focused pytest로 RED 확인

### Task 2: Minimal interpretation implementation

**Files:**
- Modify: `chatbot/src/onboarding/codebase_mapper.py`

**Step 1:** interpretation schema와 writer 추가
**Step 2:** candidate validation/fallback 구현
**Step 3:** focused pytest로 GREEN 확인

### Task 3: Patch planner integration

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/src/onboarding/orchestrator.py`
- Modify: `chatbot/tests/onboarding/test_agent_integration.py`

**Step 1:** ranked candidates 우선 사용 테스트 추가
**Step 2:** orchestrator가 interpretation artifact 생성하도록 연결
**Step 3:** integration test 녹색 확인

### Task 4: Summary surface

**Files:**
- Modify: `chatbot/src/onboarding/slack_bridge.py`
- Modify: `chatbot/tests/onboarding/test_slack_bridge.py`

**Step 1:** summary 노출 테스트 추가
**Step 2:** minimal surface 추가

### Task 5: Full verification

**Step 1:** onboarding pytest 전체 실행
**Step 2:** py_compile 실행
