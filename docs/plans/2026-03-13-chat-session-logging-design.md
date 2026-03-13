# Chat Session Logging Design

**Context**

`chatbot` 서비스는 스트리밍 응답과 실행 타임라인 로그는 이미 보유하고 있지만, SFT/DPO 학습에 바로 활용할 수 있는 세션 원본 로그와 사용자 선호 라벨(`good`/`bad`)은 구조화되어 있지 않다.

**Goal**

세션 진행 중의 질문/답변 이력을 JSON으로 누적 저장하고, 사용자가 `good` 또는 `bad`를 누르는 순간 해당 세션을 종료 처리하여 학습용으로 재사용 가능한 원본 데이터를 안정적으로 남긴다.

**Decisions**

1. 운영 원본은 세션 단위 JSON으로 저장한다.
2. 학습용 질문/답변 pair는 원본 세션 JSON에서 파생 생성한다.
3. 피드백은 답변 단위가 아니라 세션 종료 이벤트로 저장한다.
4. 로그에 저장할 `state`는 선택 가능한 필드만 기록하도록 구성해 유지보수를 단순화한다.

**Stored Session Shape**

```json
{
  "conversation_id": "conv_xxx",
  "user_id": 12,
  "status": "completed",
  "feedback_label": "good",
  "messages": [
    {"role": "user", "content": "배송 언제 와?", "at": "2026-03-13T10:00:00Z"},
    {"role": "assistant", "content": "내일 도착 예정입니다.", "at": "2026-03-13T10:00:02Z"}
  ],
  "selected_state": {
    "order_context": {},
    "search_context": {},
    "conversation_summary": null,
    "completed_tasks": []
  },
  "training_pairs": [
    {
      "turn_index": 0,
      "input": "배송 언제 와?",
      "output": "내일 도착 예정입니다."
    }
  ],
  "started_at": "2026-03-13T10:00:00Z",
  "ended_at": "2026-03-13T10:00:10Z",
  "reset_required": true
}
```

**Selected State Policy**

로깅 대상 상태는 상수 또는 선택 함수로 한 곳에서 관리한다. 기본 후보는 아래다.

- `conversation_summary`
- `order_context`
- `search_context`
- `completed_tasks`
- `ui_action_required`
- `llm_provider`
- `llm_model`
- `site_id`

민감하거나 학습에 불필요한 필드는 기본적으로 제외한다.

**API Behavior**

1. `/stream`
   각 요청이 끝날 때 해당 턴의 `user`/`assistant` 메시지와 선택 상태를 세션 로그에 누적한다.
2. `/feedback`
   `conversation_id`와 `feedback_label`을 받아 세션을 종료 처리하고 최종 JSON을 확정 저장한다.
3. `/feedback` 응답
   프론트엔드가 상태와 history를 비울 수 있도록 `reset_required: true`를 반환한다.

**Error Handling**

- 피드백 대상 세션이 없으면 `404`
- 잘못된 라벨이면 스키마 검증으로 `422`
- 세션이 이미 종료되었으면 중복 종료를 방지하거나 멱등적으로 동일 응답을 반환

**Testing**

- 세션 로그가 질문/답변 순서로 누적되는지
- 선택 상태가 지정된 키만 기록되는지
- 세션 종료 시 `feedback_label`, `training_pairs`, `reset_required`가 기록되는지
- `/feedback` 응답이 프론트 초기화 신호를 주는지
