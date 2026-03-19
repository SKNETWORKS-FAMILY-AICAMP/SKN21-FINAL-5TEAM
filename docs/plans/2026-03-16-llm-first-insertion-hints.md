# LLM-First Insertion Hints Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** LLM proposal이 파일별 삽입 위치 힌트를 생성하고 patch draft가 이를 우선 사용하도록 만든다.

**Architecture:** proposal 단계에서 후보 파일 샘플과 함께 `insertion_hint`를 생성하고, patch writer는 hint가 유효하면 그 위치에 삽입한다. 유효하지 않으면 기존 deterministic 삽입 위치 계산으로 fallback한다.

**Tech Stack:** Python, pydantic, pytest

---

### Task 1: Failing tests for hint-aware patch draft

**Files:**
- Modify: `chatbot/tests/onboarding/test_patch_planner.py`

**Step 1:** views/urlconf/frontend 각각 `insertion_hint` 기반 삽입 테스트 작성
**Step 2:** invalid hint fallback 테스트 작성
**Step 3:** focused pytest로 RED 확인

### Task 2: Minimal patch writer support

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`

**Step 1:** proposal target schema에 `insertion_hint` 추가
**Step 2:** patch writer가 hint를 우선 사용하도록 최소 구현
**Step 3:** focused pytest로 GREEN 확인

### Task 3: LLM proposal input enrichment

**Files:**
- Modify: `chatbot/src/onboarding/patch_planner.py`
- Modify: `chatbot/tests/onboarding/test_patch_planner.py`

**Step 1:** file sample 포함 테스트 추가
**Step 2:** LLM prompt payload에 source snippets 추가
**Step 3:** validation 추가

### Task 4: Full verification

**Step 1:** full onboarding pytest
**Step 2:** py_compile
