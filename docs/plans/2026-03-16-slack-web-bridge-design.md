# Slack Web Bridge Design

## Goal

onboarding run이 진행될 때 `run_onboarding_generation()`이 직접 Slack Web API로 thread 메시지를 발행하도록 만든다. 실행 직후 root message, agent message, approval button message가 실제 Slack 채널에 보여야 하며, Socket Mode gateway는 버튼 클릭을 받아 같은 thread에 decision 기록 메시지를 남길 수 있어야 한다.

## Scope

이번 단계에서 구현할 항목:

- `SlackWebBridge` 추가
- root message `ts`를 `run_id -> thread_ts`로 저장
- `post_run_root`, `post_agent_message`, `post_approval_request`, `record_approval_decision`를 실제 `chat.postMessage`로 발행
- `run_onboarding_generation()`에서 bridge 주입 시 즉시 Slack 발행
- gateway가 decision 기록 후 같은 thread에 메시지 남기기
- 실행 로그 추가

이번 단계에서 제외:

- Slack reply text parsing
- multi-channel routing
- persistent thread mapping DB
- Slack message update / delete

## Core Decision

메시지 발행은 별도 bridge runner가 아니라 `run_onboarding_generation()` 내부에서 직접 수행한다.

- run 실행이 시작되면 즉시 Slack에서 진행 상태를 볼 수 있어야 한다.
- 현재 구조는 이미 bridge 메서드 호출 지점이 orchestrator에 들어가 있으므로 실제 구현체만 바꾸면 된다.
- `thread_ts`만 안정적으로 관리하면, root message 이후 모든 메시지를 같은 Slack thread로 묶을 수 있다.

## Architecture

구성 요소는 아래 3개다.

1. `SlackWebBridge`
   - `slack_sdk.web.WebClient` 래퍼
   - thread root 생성
   - approval button blocks 생성
   - `run_id -> thread_ts` 메모리 매핑 유지

2. `run_onboarding_generation()`
   - bridge가 있으면 root/agent/approval/export 메시지를 바로 발행
   - 기존 `InMemorySlackBridge`와 동일한 인터페이스를 사용

3. `Slack Socket Gateway`
   - approval store에 decision 기록
   - `SlackWebBridge.record_approval_decision()` 형태의 thread message를 추가로 발행 가능

## Data Flow

1. `run_onboarding_generation()` 시작
2. `SlackWebBridge.post_run_root()`가 채널에 root message 발행
3. 반환된 `ts`를 `thread_ts`로 저장
4. Analyzer/Planner/Generator/Validator/Diagnostician 메시지는 모두 해당 `thread_ts`로 발행
5. approval request는 button block이 포함된 메시지로 같은 thread에 발행
6. Socket gateway가 클릭을 처리하면 approval store를 갱신
7. gateway는 같은 `run_id`의 `thread_ts`를 알고 있으면 decision 기록 메시지를 발행

## Thread Mapping

초기 구현은 메모리 + file fallback으로 간다.

- runtime map: `dict[run_id, thread_ts]`
- optional file report: `generated/<site>/<run_id>/reports/slack-thread.json`

이유:

- 같은 프로세스 내에서는 메모리 lookup이 가장 단순하다.
- run 종료 후에도 thread_ts를 확인할 수 있도록 report 파일을 남기면 gateway나 디버깅에 유리하다.

## Slack Message Shape

### Root Message

- channel
- text
- metadata-like summary fields in plain text body

### Agent Message

- role
- claim
- evidence
- confidence
- risk
- next_action
- blocking_issue

### Approval Message

- summary
- recommended_option
- risk_if_approved
- risk_if_rejected
- two buttons: Approve / Reject

버튼 `value`는 JSON 문자열로 유지한다.

## Logging

최소 로그는 stdout에 남긴다.

- gateway started
- socket connected
- approval action received
- approval decision recorded
- slack message posted

## Testing Strategy

1. `SlackWebBridge` 단위 테스트
   - root message post 시 thread_ts 저장
   - agent/approval message가 같은 thread로 가는지
   - button blocks shape 검증

2. orchestrator integration 테스트
   - fake web client에 메시지가 순서대로 쌓이는지
   - approval request가 실제 button block을 가지는지

3. gateway integration 테스트
   - decision 기록 후 thread message post 호출되는지

## Success Criteria

- onboarding run 시작 시 Slack 채널에 root message가 보인다.
- 같은 run의 후속 메시지가 모두 같은 thread에 쌓인다.
- approval request에 실제 Slack 버튼 block이 포함된다.
- button 클릭 후 decision 기록 메시지가 thread에 남는다.
- 관련 테스트가 외부 네트워크 없이 재현 가능하다.
