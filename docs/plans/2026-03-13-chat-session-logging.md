# Chat Session Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 세션 단위 대화 로그와 `good`/`bad` 종료 피드백을 저장하고, 학습용 질문/답변 pair를 함께 생성한다.

**Architecture:** 기존 `ConversationRunLogger`는 실행 타임라인 로그 역할을 유지하고, 별도의 세션 로그 기능을 같은 모듈 안에 추가한다. `/stream`은 턴 종료 시 세션 로그를 append 하고 `/feedback`는 세션 종료 및 reset 응답을 담당한다.

**Tech Stack:** FastAPI, Pydantic, JSON/JSONL file logging, pytest

---

### Task 1: 문서와 스키마 정의

**Files:**
- Modify: `chatbot/src/schemas/chat.py`

**Step 1: Write the failing test**

세션 종료 요청이 `conversation_id`와 `feedback_label`을 요구한다는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_session_logging.py -k feedback_schema -v`
Expected: FAIL because schema or test target does not exist.

**Step 3: Write minimal implementation**

`FeedbackRequest` 스키마를 추가한다.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_session_logging.py -k feedback_schema -v`
Expected: PASS

**Step 5: Commit**

이번 작업에서는 별도 커밋 생략.

### Task 2: 세션 로그 도메인 구현

**Files:**
- Modify: `chatbot/src/infrastructure/conversation_logger.py`
- Test: `tests/test_chat_session_logging.py`

**Step 1: Write the failing test**

세션 로그 생성, 메시지 누적, 선택 상태 필터링, 학습용 pair 생성 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_session_logging.py -k session_logger -v`
Expected: FAIL because session logger API does not exist.

**Step 3: Write minimal implementation**

`SessionConversationLogger`와 상태 선택 헬퍼를 구현한다.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_session_logging.py -k session_logger -v`
Expected: PASS

**Step 5: Commit**

이번 작업에서는 별도 커밋 생략.

### Task 3: 스트리밍 엔드포인트 연동

**Files:**
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Test: `tests/test_chat_session_logging.py`

**Step 1: Write the failing test**

턴 완료 시 세션 로그에 질문/답변이 저장되는 동작을 헬퍼 단위로 검증하는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_session_logging.py -k stream_logging -v`
Expected: FAIL because integration helper does not exist.

**Step 3: Write minimal implementation**

스트림 종료 후 `final_state` 기반으로 세션 로그 append 헬퍼를 호출한다.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_session_logging.py -k stream_logging -v`
Expected: PASS

**Step 5: Commit**

이번 작업에서는 별도 커밋 생략.

### Task 4: 피드백 종료 API 구현

**Files:**
- Modify: `chatbot/src/api/v1/endpoints/chat.py`
- Test: `tests/test_chat_session_logging.py`

**Step 1: Write the failing test**

`good`/`bad` 피드백으로 세션 종료 시 `reset_required: true`와 종료 로그가 기록되는 테스트를 추가한다.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_session_logging.py -k feedback_endpoint -v`
Expected: FAIL because endpoint does not exist.

**Step 3: Write minimal implementation**

`/feedback` 엔드포인트와 종료 처리 로직을 구현한다.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_session_logging.py -k feedback_endpoint -v`
Expected: PASS

**Step 5: Commit**

이번 작업에서는 별도 커밋 생략.

### Task 5: 전체 검증

**Files:**
- Test: `tests/test_chat_session_logging.py`

**Step 1: Run focused test suite**

Run: `pytest tests/test_chat_session_logging.py -v`
Expected: PASS

**Step 2: Run any safe adjacent checks if needed**

Run: `pytest tests/test_chat_session_logging.py -k pair -v`
Expected: PASS

**Step 3: Review outputs**

실패/누락 없이 새 기능 요구사항을 충족하는지 확인한다.

**Step 4: Commit**

이번 작업에서는 별도 커밋 생략.
