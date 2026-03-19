# LLM-First Role Runner Design

## Goal
모든 onboarding 역할 에이전트가 기본적으로 LLM을 먼저 사용하고, 실패 시 deterministic fallback으로 계속 진행하는 안정적인 실행 경로를 만든다.

## Current State
- `Analyzer`, `Planner`, `Generator`, `Validator`, `Diagnostician`는 `RoleRunner` 또는 `LLMRoleRunner` 중 하나로만 실행된다.
- `--use-llm-roles`를 켜면 전부 LLM 경로로 바뀌지만, JSON 파싱 실패나 provider 예외 시 run이 그대로 깨질 수 있다.
- 현재는 `llm-proposed.patch`와 `llm-patch-simulation.json`은 비교용으로 존재하지만, role 단계 자체의 LLM 신뢰성 기록은 없다.

## Target Behavior
- 모든 role 호출은 기본적으로 `LLM -> deterministic fallback` 순서로 시도한다.
- LLM 응답이 유효하면 그 결과를 채택한다.
- LLM 호출 실패, invalid JSON, 필수 필드 누락 시 deterministic responder로 자동 전환한다.
- 각 role별 실행 provenance를 `reports/llm-role-execution.json`에 기록한다.
- Slack summary와 최종 결과에서 fallback 발생 여부를 확인할 수 있게 한다.

## Architecture
- 새 `ReliableLLMRoleRunner`를 추가한다.
- 내부 구성:
  - `llm_runner`: 기존 `LLMRoleRunner`
  - `fallback_runner`: 기존 `RoleRunner`
  - `execution_log`: role별 `source`, `fallback_reason`, `error_type` 기록
- `run_onboarding_generation`은 `use_llm_roles`가 켜지면 strict LLM 전용이 아니라 reliable runner를 사용한다.
- 실행 종료 시 `reports/llm-role-execution.json`을 저장하고, summary artifact 집합에 포함한다.

## Failure Policy
- fallback 조건:
  - LLM invoke exception
  - invalid JSON
  - 필수 키 누락
  - unsupported payload shape
- fallback은 run을 중단시키지 않는다.
- 단, fallback 발생 사실은 artifact로 남긴다.

## Testing
- role별 LLM 성공 시 source=`llm`
- role별 LLM 실패 시 source=`fallback`
- JSON parse failure / missing field failure 모두 deterministic responder로 이어짐
- `run_onboarding_generation(... use_llm_roles=True ...)`에서도 run이 끝까지 완료됨
- `llm-role-execution.json` 생성 및 Slack summary 반영 확인

## Tradeoff
- 장점: 실제 LLM 사용을 기본화하면서 파이프라인 안정성을 유지한다.
- 단점: fallback이 많으면 겉보기엔 LLM-first지만 실제 성능은 deterministic에 기대게 된다.
- 그래서 provenance artifact가 필수다.
