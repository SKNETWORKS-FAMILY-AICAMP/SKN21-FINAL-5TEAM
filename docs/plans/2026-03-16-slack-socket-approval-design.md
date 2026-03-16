# Slack Socket Approval Design

## Goal

Slack Socket Mode를 사용해 onboarding agent의 승인 게이트를 실제 Slack 앱과 양방향으로 연결한다. 사용자는 Slack thread에서 버튼을 눌러 `analysis`, `apply`, `export` 승인을 처리하고, orchestrator는 이 결정을 안전하게 반영해야 한다.

## Scope

이번 단계의 범위는 아래로 제한한다.

- Slack `Socket Mode` 연결
- approval request를 Slack interactive button 메시지로 게시
- 버튼 클릭 이벤트 수신
- `run_id + approval_type` 기준 approval decision 기록
- orchestrator가 recorded decision을 읽어 gate 진행

이번 단계에서 제외한다.

- Slack reply text 기반 승인
- 공개 HTTP callback endpoint
- 다중 워커 분산 락
- 실제 GitHub PR 생성

## Core Decision

Slack 수신은 orchestrator 내부가 아니라 별도 gateway 프로세스로 분리한다.

- orchestrator는 run 실행과 상태 전이에만 집중한다.
- Slack gateway는 Socket Mode 연결과 action 수신에만 집중한다.
- 두 프로세스는 approval store를 통해 느슨하게 연결된다.

이 구조가 맞는 이유는 Slack 연결 상태와 run 상태를 분리해야 장애 범위가 작고, 테스트도 deterministic 하게 유지할 수 있기 때문이다.

## Architecture

구성 요소는 4개다.

1. `SlackSocketBridge`
   - Slack Web API와 Socket Mode client를 감싼다.
   - approval request를 thread message + action button으로 게시한다.
   - interactive action payload를 parse한다.

2. `Slack Socket Gateway`
   - 별도 프로세스로 실행된다.
   - Slack action 수신 시 approval store에 decision을 쓴다.
   - 같은 결정을 중복 기록하지 않도록 idempotent 처리한다.

3. `ApprovalStore`
   - `run_id`, `approval_type`, `status`, `decision`, `decided_at`, `actor`를 저장한다.
   - orchestrator와 gateway가 함께 읽고 쓴다.
   - MVP에서는 로컬 파일 기반 JSON 저장소로 시작한다.

4. `Orchestrator Polling Adapter`
   - approval gate 진입 시 pending request를 store에 기록한다.
   - polling으로 decision을 읽어 승인 상태를 반영한다.
   - 처리 후 해당 decision을 `consumed`로 바꾼다.

## Data Flow

1. orchestrator가 approval request를 생성한다.
2. Slack bridge가 thread에 버튼 메시지를 게시한다.
3. 같은 approval request가 approval store에도 `pending`으로 기록된다.
4. 사용자가 Slack에서 `Approve` 또는 `Reject` 버튼을 누른다.
5. Socket gateway가 action payload를 받아 approval store를 `approved` 또는 `rejected`로 갱신한다.
6. orchestrator가 polling으로 결정을 읽는다.
7. orchestrator가 현재 gate에 결정을 반영하고 상태를 전이한다.
8. bridge가 thread에 `decision applied` 메시지를 남긴다.
9. approval store는 해당 요청을 `consumed` 상태로 바꾼다.

## Slack Payload Design

approval request 버튼 payload는 최소 필드를 가진다.

- `run_id`
- `approval_type`
- `decision`
- `request_id`

버튼은 두 개만 둔다.

- `Approve`
- `Reject`

Slack message 본문에는 아래를 포함한다.

- approval summary
- recommended option
- risk if approved
- risk if rejected
- run id

## Approval Store Design

초기 저장 형식은 JSON 파일이다.

파일 단위:

- `generated/<site>/<run_id>/reports/approval-store.json`
  또는
- 별도 공용 루트 `generated/approvals/<run_id>.json`

이번 단계 추천은 공용 루트다.

이유:

- run 폴더가 아직 생성되지 않았거나 다른 프로세스에서 바로 접근하기 쉬움
- Slack gateway가 site/source context를 몰라도 기록 가능

레코드 형태:

```json
{
  "request_id": "food-run-001:apply",
  "run_id": "food-run-001",
  "approval_type": "apply",
  "status": "pending",
  "decision": null,
  "actor": null,
  "requested_at": "2026-03-16T10:00:00+09:00",
  "decided_at": null,
  "consumed_at": null
}
```

상태:

- `pending`
- `approved`
- `rejected`
- `consumed`

## Failure Handling

MVP에서 중요하게 막아야 하는 실패는 아래다.

- 중복 클릭
- 오래된 request에 대한 늦은 승인
- 이미 consumed 된 request 재처리
- 다른 approval type에 대한 잘못된 클릭

정책:

- `request_id` 기준으로 idempotent 처리
- pending 상태가 아니면 overwrite 금지
- consumed 상태에서는 action을 무시하고 Slack에 warning ack
- orchestrator는 timeout 시 local CLI approval fallback 없이 그대로 pending 유지

## Security Model

최소 보안 원칙은 아래다.

- Slack app token과 bot token은 env var로만 주입
- action payload는 Socket Mode client가 전달한 이벤트만 신뢰
- store write 시 `actor`에 Slack user id 저장
- 승인 로그는 run reports와 Slack thread 모두에 남긴다.

## Testing Strategy

테스트는 외부 Slack API 호출 없이 3단으로 나눈다.

1. approval store 단위 테스트
   - create request
   - record decision
   - consume decision
   - idempotency

2. Slack payload / action handler 테스트
   - button block payload 생성
   - action payload parse
   - approve/reject 기록

3. orchestrator integration 테스트
   - pending approval 생성
   - simulated decision 반영
   - state transition 확인

실제 Slack SDK 연결 테스트는 thin wrapper 수준으로만 추가한다.

## Recommended Implementation Order

1. approval store 추가
2. Slack bridge에 button payload 추가
3. Socket gateway action handler 추가
4. orchestrator polling adapter 연결
5. CLI / demo runner 추가

## Success Criteria

- Slack button click이 approval store에 기록된다.
- orchestrator가 polling으로 그 결정을 반영한다.
- `analysis`, `apply`, `export` 3개 approval type이 모두 같은 경로로 처리된다.
- 중복 클릭은 상태를 오염시키지 않는다.
- 관련 테스트가 네트워크 없이 재현 가능하다.
