# Order CS Subagents Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the monolithic `ORDER_CS` ReAct subagent with action-specific order nodes so cancel/refund/exchange/shipping no longer compete inside one agent loop and waiting-user states stop the graph cleanly.

**Architecture:** Keep the top-level `planner` and `supervisor` for cross-domain task orchestration, but split the order flow into `order_entry -> order_intent_router -> action-specific subagent`. Each order action node invokes only its own tool path and returns an explicit `completed | waiting_user | failed` status for workflow routing.

**Tech Stack:** Python, FastAPI, LangGraph, LangChain tools, pytest

---

### Task 1: Add regression tests for order routing and stop conditions

**Files:**
- Create: `tests/test_order_graph_routing.py`
- Modify: `chatbot/src/graph/state.py`
- Modify: `chatbot/src/graph/workflow.py`

**Step 1: Write the failing test**

```python
def test_order_router_routes_cancel_keywords_to_cancel_subagent():
    ...

def test_order_router_preserves_pending_action_during_resume():
    ...

def test_order_result_waiting_user_stops_at_final_generator():
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_order_graph_routing.py -v`
Expected: FAIL because order router / routing helpers do not exist yet.

**Step 3: Write minimal implementation**

Add order routing helpers and workflow conditional edges needed by the tests.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_order_graph_routing.py -v`
Expected: PASS

### Task 2: Replace `order_subagent` with order entry, intent router, and action nodes

**Files:**
- Create: `chatbot/src/graph/nodes/order_flow.py`
- Modify: `chatbot/src/graph/nodes/supervisor.py`
- Modify: `chatbot/src/graph/workflow.py`
- Modify: `chatbot/src/api/v1/endpoints/chat.py`

**Step 1: Write the failing test**

```python
def test_cancel_node_invokes_only_cancel_tool():
    ...

def test_refund_node_marks_waiting_user_when_ui_action_exists():
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_order_graph_routing.py -v`
Expected: FAIL because action-specific nodes do not exist yet.

**Step 3: Write minimal implementation**

Create shared helpers for order node updates, add `order_entry`, `order_intent_router`, `cancel_subagent`, `refund_subagent`, `exchange_subagent`, `shipping_subagent`, and wire them into the workflow.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_order_graph_routing.py -v`
Expected: PASS

### Task 3: Update session state and final generation compatibility

**Files:**
- Modify: `chatbot/src/graph/state.py`
- Modify: `chatbot/src/graph/nodes/final_generator.py`
- Test: `tests/test_order_graph_routing.py`

**Step 1: Write the failing test**

```python
def test_order_completed_action_records_order_cs_result():
    ...

def test_order_waiting_user_keeps_ui_action_without_general_chat_fallback():
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_order_graph_routing.py -v`
Expected: FAIL because the new order action state is not normalized yet.

**Step 3: Write minimal implementation**

Normalize `order_context` state updates so `ORDER_CS` stays the completed task key while action-specific nodes drive routing and UI behavior.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_order_graph_routing.py -v`
Expected: PASS

### Task 4: Run focused regression verification

**Files:**
- Test: `tests/test_order_graph_routing.py`
- Test: `tests/integration/test_order_tools.py`

**Step 1: Run focused tests**

Run: `pytest tests/test_order_graph_routing.py tests/integration/test_order_tools.py -v`

**Step 2: Fix any breakage**

Adjust minimal code only if regressions appear.

**Step 3: Re-run verification**

Run: `pytest tests/test_order_graph_routing.py tests/integration/test_order_tools.py -v`
Expected: PASS
