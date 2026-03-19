# Guardrail Safe-Only Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Guardrail startup 시 실제 클래스 수와 라벨 매핑을 로그로 남기고, `safe` 라벨만 통과시키도록 고정한다.

**Architecture:** `chatbot/src/graph/nodes/guardrail.py`에서 모델 로드 직후 `id2label` 메타데이터를 읽어 로깅한다. 분류 노드는 신뢰도 임계값 대신 최상위 라벨이 `safe`인지 여부만 기준으로 통과/차단을 결정한다.

**Tech Stack:** Python, pytest, transformers pipeline, FastAPI startup preload

---

### Task 1: Guardrail Regression Tests

**Files:**
- Modify: `chatbot/tests/test_guardrail_startup.py`
- Test: `chatbot/tests/test_guardrail_startup.py`

**Step 1: Write the failing test**

Add tests that verify:
- `load_guardrail_model()` logs loaded class count and `id2label` mapping text.
- `guardrail_node()` passes only when the predicted label is `safe`.
- Non-`safe` labels are blocked regardless of score.

**Step 2: Run test to verify it fails**

Run: `uv run pytest chatbot/tests/test_guardrail_startup.py -q`
Expected: FAIL because current implementation does not log label mapping and still uses confidence threshold-based pass-through.

**Step 3: Write minimal implementation**

Update `chatbot/src/graph/nodes/guardrail.py` to:
- Extract model label metadata after pipeline load.
- Log class count plus `id -> label` text.
- Remove confidence-threshold pass-through for non-`safe` labels.

**Step 4: Run test to verify it passes**

Run: `uv run pytest chatbot/tests/test_guardrail_startup.py -q`
Expected: PASS
