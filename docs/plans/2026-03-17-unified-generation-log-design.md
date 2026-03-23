# Unified Generation Log Design

## Goal
온보딩 generation 실행 전체를 시간순으로 한 통에서 추적할 수 있는 단일 로그 파일을 추가한다.

## Problem
현재는 `execution-trace.jsonl`, `llm-debug/*.json`, `llm-usage.json`, 터미널 출력이 분산되어 있다. 단계별 artifact는 남지만 "어느 시점에 어떤 단계가 시작됐고, 어떤 파일이 생성됐고, 어떤 fallback이 발생했는지"를 한 번에 보기 어렵다.

## Recommended Approach
`run_root/reports/generation.log`를 append-only timeline 원본으로 추가한다.

- 모든 주요 단계는 사람 친화적인 한 줄 로그를 `generation.log`에 기록한다.
- 기존 `execution-trace.jsonl`은 기계용 이벤트로 유지한다.
- 기존 `llm-debug/*.json`은 상세 payload 저장소로 유지한다.
- 터미널 출력은 `generation.log`와 같은 메시지를 미러링한다.

## Alternatives Considered

### 1. Extend `execution-trace.jsonl`
- 장점: 기존 artifact 재사용
- 단점: 기계용 이벤트와 사람이 읽는 로그가 섞여 가독성이 나빠진다.

### 2. Capture terminal output only
- 장점: 구현이 단순하다
- 단점: 구조화 정보가 약하고 파일 생성/디버그 artifact 경로 같은 핵심 정보를 안정적으로 남기기 어렵다.

### 3. Add dedicated `generation.log`
- 장점: 시간순 관측성이 가장 좋고 기존 artifact 체계를 유지할 수 있다
- 단점: 로그 기록 호출 지점을 몇 군데 추가해야 한다

권장안은 3번이다.

## Log Format
각 줄은 단일 이벤트를 나타낸다.

예시:

```text
2026-03-17T00:13:24.439196+00:00 INFO orchestrator analysis_started site=food source_root=/path/to/source
2026-03-17T00:13:24.500000+00:00 INFO codebase_mapper codebase_map_written path=/.../reports/codebase-map.json candidate_count=17
2026-03-17T00:13:24.600000+00:00 INFO codebase_mapper llm_codebase_interpretation_started provider=openai model=gpt-5-mini
2026-03-17T00:13:25.000000+00:00 WARN codebase_mapper llm_codebase_interpretation_fallback reason=invalid_llm_payload debug_path=/.../reports/llm-debug/codebase-interpretation.json
2026-03-17T00:13:25.100000+00:00 INFO role_runner role_completed role=Analyzer source=llm fallback_reason=none
```

필수 요소:
- timestamp
- level
- component
- event
- message or key/value context

## Scope

### Must log
- generation 시작
- analysis 시작/완료
- `codebase-map.json` 생성
- LLM codebase interpretation 시작/성공/fallback
- role 실행 시작/완료/fallback
- patch proposal 생성
- patch draft 생성
- simulation 시작/완료
- smoke test 시작/완료
- export/review 관련 최종 상태

### Should log
- 생성되거나 갱신된 주요 파일 경로
- fallback reason
- debug artifact 경로
- llm usage summary

### Out of scope
- 모든 내부 함수 호출의 세부 trace
- 전체 raw response를 `generation.log`에 직접 덤프하는 것

raw payload는 계속 `llm-debug/*.json`에 저장하고, `generation.log`에는 해당 경로만 기록한다.

## Architecture

### Logging primitives
`debug_logging.py`에 단일 timeline 파일 writer를 추가한다.

- `append_generation_log(report_root, level, component, event, message, details)`
- 출력 대상: `reports/generation.log`
- `details`는 `key=value` 문자열로 직렬화

### Terminal mirroring
orchestrator의 `terminal_logger`는 유지하되, 동일한 메시지를 파일에도 남기도록 통합 헬퍼를 둔다.

- 사람용 로그는 파일이 원본
- 터미널은 파일 로그의 미러

### LLM debug integration
`write_llm_debug_artifact()` 호출 지점에서 debug artifact 경로를 generation log에 남긴다.
특히 codebase interpretation은 현재 raw response artifact가 없으므로 추가한다.

## Data Flow
1. `run_onboarding_generation()`이 `run_root`를 만든다.
2. 각 단계가 시작될 때 `generation.log`에 시작 이벤트를 append한다.
3. 산출물 작성 직후 파일 경로를 append한다.
4. LLM 단계는 raw response/normalized response/debug artifact 저장 후 해당 경로를 append한다.
5. fallback이나 validation error가 발생하면 reason과 영향 범위를 append한다.
6. 필요 시 동일 메시지를 `terminal_logger`로 전달한다.

## Testing Strategy

### Unit tests
- `append_generation_log()`가 파일을 생성하고 시간순 append하는지 검증
- structured details가 기대 포맷으로 직렬화되는지 검증

### Integration tests
- onboarding run 결과에 `generation_log_path`가 포함되는지 검증
- LLM codebase interpretation fallback 시 `generation.log`에 fallback line과 debug artifact path가 남는지 검증
- patch proposal, role completion 같은 주요 단계가 한 파일에 순서대로 남는지 검증

## Risks
- 로그 중복: terminal log와 generation log가 같은 메시지를 두 번 구성하지 않도록 공통 writer를 둬야 한다.
- 과도한 로그량: raw payload는 debug artifact에 남기고 `generation.log`에는 요약만 남겨야 한다.
- 테스트 취약성: 타임스탬프 전체 문자열 비교 대신 event 존재와 순서를 검증해야 한다.

## Success Criteria
- 사용자는 `run_root/reports/generation.log` 하나만 열어 generation 전체 흐름을 시간순으로 파악할 수 있다.
- fallback 시점과 원인, 관련 debug artifact 경로를 즉시 찾을 수 있다.
- 기존 JSON artifact 체계는 유지되어 상세 분석이 가능하다.
