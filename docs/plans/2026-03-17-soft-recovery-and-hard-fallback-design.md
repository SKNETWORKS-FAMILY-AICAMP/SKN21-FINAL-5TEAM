# Soft Recovery And Hard Fallback Design

## Goal
LLM-first onboarding 파이프라인이 validation 실패 시 즉시 deterministic fallback으로 떨어지지 않고, 가능한 경우 실행용 데이터를 복구해 계속 진행하도록 만든다. 복구 불가능한 경우에는 `hard_fallback`을 명확히 기록하고 노출한다.

## Problem
현재는 LLM 응답이 schema를 조금만 벗어나도 바로 fallback으로 전환된다. 이 방식은 실행 안정성은 높지만, 실제로는 복구 가능한 응답도 모두 deterministic 경로로 밀어내고 있다. 또한 `fallback` 하나로는 "정말 실패해서 안전 경로로 간 경우"와 "작은 formatting 문제만 있었던 경우"를 구분할 수 없다.

## Source Model
모든 LLM-first 단계는 아래 세 가지 source 상태 중 하나를 가져야 한다.

- `llm`
- `recovered_llm`
- `hard_fallback`

### Meaning
- `llm`: 원본 LLM 응답이 strict validation을 그대로 통과
- `recovered_llm`: 원본 응답은 strict validation 실패, 하지만 recovery layer가 실행용 형식으로 재정렬해서 재검증 통과
- `hard_fallback`: recovery도 실패해서 deterministic 안전 경로 사용

## Recovery Philosophy
- 실행은 가능한 한 계속 진행한다.
- 코드베이스를 자동 수정하지 않는다.
- recovery는 실행용 payload/patch artifact를 정규화하는 역할만 한다.
- 실제 프롬프트/스키마/코드 수정은 사람이 artifact를 보고 수행한다.

즉, recovery는 문제를 숨기기 위한 장치가 아니라 실행 continuity와 진단 가능성을 동시에 확보하기 위한 계층이다.

## Architecture

### Recovery Layer
새 공통 recovery layer를 도입한다.

입력:
- `component`
- `fallback_reason`
- `raw_response`
- `validation_error`
- `context`

출력:
- `source`
- `recovered_payload` 또는 `recovered_patch`
- `recovery_applied`
- `recovery_reason`
- `hard_fallback_reason`
- `recovery_notes`

### Flow
1. 원본 LLM 호출
2. strict validation
3. 실패 시 recovery layer 호출
4. recovery 결과 재검증
5. 성공 시 `source=recovered_llm`
6. 실패 시 `source=hard_fallback`

## Component Scope

### 1. `llm_codebase_interpretation`
- 문자열/객체 흔들림
- 일부 필드 누락
- conservative candidate normalization

### 2. `ReliableLLMRoleRunner`
- `confidence` / `risk` / `next_action` 타입 흔들림
- nullable/scalar/list normalization
- metadata shape 보정

### 3. `llm_patch_proposal`
- JSON shape 복구
- target file selection 재검증
- invalid path는 recovery로 숨기지 않고 `hard_fallback`

### 4. `llm_patch_draft`
- fenced diff 제거
- trailing newline 보정
- trivial formatting 복구만 허용
- hunk 구조가 불완전하거나 target 범위가 틀리면 `hard_fallback`

patch draft는 의미적 위험이 가장 크므로 recovery 범위를 가장 보수적으로 둔다.

## Artifact Changes

### Existing artifacts
기존 execution/debug artifact에 아래 필드를 추가한다.

- `source`
- `recovery_applied`
- `recovery_reason`
- `hard_fallback_reason`
- `validation_error`
- `recovered_response` 또는 `recovered_payload`

### New artifact
- `reports/recovery-events.json`

이 파일은 component별 recovery 결과를 append-only로 모은다.

예시:

```json
{
  "component": "llm_codebase_interpretation",
  "source": "recovered_llm",
  "recovery_reason": "framework_assessment_string_to_dict",
  "hard_fallback_reason": null
}
```

## Logging

### generation.log
아래 이벤트를 추가한다.

- `recovery_started`
- `recovery_succeeded`
- `hard_fallback_used`

### Slack summary
summary에 source count를 별도로 노출한다.

예:
- `llm 4건`
- `recovered_llm 2건`
- `hard_fallback 1건`

`hard_fallback`은 reason을 더 강조해 thread에서도 볼 수 있게 한다.

## Why Not Validator
`Validator`는 smoke 결과와 최종 산출물을 평가하는 후행 역할이다. fallback 직전 응답 복구는 validation이 아니라 pre-validation normalization 문제다. 따라서 Validator에 넣으면 책임이 섞인다.

## Why Not Reuse Diagnostician Directly
`Diagnostician`은 validation failure 이후 root cause analysis와 retry 판단을 담당한다. pre-fallback 응답 복구를 그대로 넣으면 범위가 과도하게 넓어진다. recovery layer는 middleware에 더 가깝다.

## Recommended Approach
전용 recovery layer를 두고 component별 soft normalization policy를 연결한다. 모든 `fallback`을 `recovered_llm` 또는 `hard_fallback`으로 분해해 provenance를 보존한다.

## Risks
- recovery가 너무 공격적이면 문제를 숨길 수 있다.
- patch draft를 과복구하면 잘못된 patch를 합법처럼 보이게 만들 수 있다.
- Slack summary에 상태가 늘어나면 처음엔 다소 복잡해질 수 있다.

## Mitigations
- recovery는 타입/포맷 정규화만 허용
- 의미적 불일치나 invalid target은 무조건 `hard_fallback`
- debug artifact에 raw/recovered 모두 저장
- `generation.log`와 Slack summary에 recovery 개입 사실을 항상 노출

## Success Criteria
- 복구 가능한 schema/format 오류는 `recovered_llm`로 계속 진행
- 복구 불가능한 경우는 `hard_fallback`으로 명확히 기록
- Slack과 artifacts에서 source distribution을 확인 가능
- 실제 프롬프트/스키마/코드 수정 포인트를 사람이 artifact만 보고 파악 가능
