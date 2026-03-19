# Onboarding Artifact Lifecycle

## 목적

이 문서는 onboarding generation 파이프라인이 어떤 순서로 artifact를 만들고, 각 파일이 어떤 입력을 받아 어떤 의미를 가지는지 정리한다.

대상 독자는 다음과 같다.

- Slack 데모를 보면서 실제 내부 생성물을 따라가고 싶은 사람
- `generated/<site>/<run-id>/`와 `runtime/<site>/<run-id>/workspace/`의 차이를 이해하고 싶은 사람
- 특정 artifact가 LLM 주도인지, deterministic인지, 검증용인지 구분하고 싶은 사람

---

## 핵심 디렉터리

### `generated/<site>/<run-id>/`

생성 결과를 보관하는 디렉터리다.

여기에는 다음이 들어간다.

- 분석/계획/검증 보고서
- patch 초안
- supporting generated files
- 최종 export 결과
- 디버깅과 추적용 로그

즉, "무엇을 만들었는가"와 "왜 그렇게 만들었는가"를 저장한다.

### `runtime/<site>/<run-id>/workspace/`

원본 사이트를 직접 수정하지 않고 merge 후 상태를 흉내 내는 임시 작업공간이다.

여기에는 다음이 반영된다.

- 원본 소스 복사본
- `generated/files/`의 supporting file
- `generated/patches/proposed.patch` 또는 비교용 patch

즉, "실제로 적용해보면 어떻게 되는가"를 확인하는 실험 공간이다.

---

## 전체 흐름

파이프라인은 크게 8단계로 artifact를 만든다.

1. run bundle 생성
2. 원본 구조 스캔
3. LLM/deterministic 해석과 역할 실행
4. patch proposal 및 supporting file 생성
5. runtime merge simulation
6. backend/frontend/smoke 검증
7. export
8. debug/trace/usage 기록

---

## 1. Run Bundle 생성

### `manifest.json`

경로 예시:

- [manifest.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/manifest.json)

생성 시점:

- `run_onboarding_generation()` 초반
- `generate_run_bundle()` 호출 직후

입력:

- `site`
- `source_root`
- `run_id`
- `agent_version`
- site analyzer 결과

의미:

- 이 run의 기본 메타데이터
- 분석 결과 초본
- 후속 단계에서 공통으로 참조하는 기준 상태

주 생성 주체:

- deterministic
- 모듈: `run_generator.py`, `manifest.py`

---

## 2. 원본 구조 스캔

### `reports/codebase-map.json`

경로 예시:

- [codebase-map.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/codebase-map.json)

생성 시점:

- manifest 로드 직후
- patch proposal 전에 항상 생성

입력:

- `source_root` 전체 텍스트 파일

의미:

- 원본 코드베이스의 raw candidate pool
- auth 후보, urlconf 후보, frontend candidate, 파일 목록 등

주 생성 주체:

- deterministic
- 모듈: `codebase_mapper.py`

비고:

- 아직 "최종 수정 대상"은 아니다
- LLM이 해석하기 전의 원시 스캔 결과다

---

## 3. LLM / 역할 실행

이 단계는 `--use-llm-roles`일 때 의미가 커진다.

### `reports/llm-codebase-interpretation.json`

경로 예시:

- [llm-codebase-interpretation.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-codebase-interpretation.json)

생성 시점:

- `codebase-map.json` 생성 직후

입력:

- `analysis`
- `codebase_map`
- file sample 일부

의미:

- raw candidate를 LLM이 해석한 결과
- `structure_summary`
- `framework_assessment`
- `ranked_candidates`

주 생성 주체:

- LLM-first
- 실패 시 deterministic fallback
- 모듈: `codebase_mapper.py`

### `reports/llm-role-execution.json`

경로 예시:

- [llm-role-execution.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-role-execution.json)

생성 시점:

- run 종료 시점에 flush

입력:

- role runner 실행 로그

의미:

- 각 role이 `llm`으로 성공했는지
- 또는 `fallback`됐는지

대상 role:

- `Analyzer`
- `Planner`
- `Generator`
- `Validator`
- `Diagnostician`

주 생성 주체:

- `ReliableLLMRoleRunner`
- 모듈: `role_runner.py`, `orchestrator.py`

### `reports/llm-debug/*.json`

경로 예시:

- [llm-debug](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-debug)
- [Analyzer.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-debug/Analyzer.json)

생성 시점:

- run 종료 시점에 role별 flush

입력:

- role별 raw LLM response
- fallback reason
- usage

의미:

- 왜 해당 role이 실패/성공했는지 직접 보는 디버깅 artifact

주 생성 주체:

- `ReliableLLMRoleRunner`
- 모듈: `role_runner.py`

비고:

- role가 실제로 실행된 경우에만 파일이 생긴다
- 예를 들어 `Analyzer`만 LLM으로 실행됐다면 `Analyzer.json`만 존재할 수 있다

---

## 4. Patch Proposal 및 Supporting File 생성

### `reports/patch-proposal.json`

경로 예시:

- [patch-proposal.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/patch-proposal.json)

생성 시점:

- analysis approval 이후
- planner / generator로 넘어가기 전후

입력:

- `analysis`
- `codebase_map`
- `llm_codebase_interpretation`
- `recommended_outputs`

의미:

- 어떤 파일을 왜 수정할지
- 어떤 supporting file이 필요한지
- analysis summary

주 생성 주체:

- LLM-first
- 실패 시 deterministic fallback
- 모듈: `patch_planner.py`

### `reports/llm-patch-proposal-execution.json`

경로 예시:

- [llm-patch-proposal-execution.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-patch-proposal-execution.json)

생성 시점:

- `patch-proposal.json` 생성과 동시에

의미:

- patch proposal 단계가 `llm` 성공인지
- `fallback`인지
- fallback reason은 무엇인지

### `files/`

경로 예시:

- [files](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/files)

대표 파일:

- [chat_auth.py](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/files/backend/chat_auth.py)
- [order_adapter_client.py](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/files/backend/order_adapter_client.py)
- [product_adapter_client.py](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/files/backend/product_adapter_client.py)

생성 시점:

- generator 결과를 materialize할 때

의미:

- 새로 추가될 supporting generated code
- patch가 아닌 별도 파일 생성물

주 생성 주체:

- deterministic scaffold/template
- generator role 결과를 바탕으로 materialize
- 모듈: `overlay_generator.py`, `template_generator.py`, `orchestrator.py`

### `patches/proposed.patch`

경로 예시:

- [proposed.patch](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/patches/proposed.patch)

생성 시점:

- `patch-proposal.json` 이후

의미:

- deterministic unified diff 초안

주 생성 주체:

- deterministic
- insertion hint가 있으면 일부 LLM 해석 반영
- 모듈: `patch_planner.py`

### `patches/llm-proposed.patch`

경로 예시:

- [llm-proposed.patch](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/patches/llm-proposed.patch)

생성 조건:

- `--generate-llm-patch-draft`

의미:

- LLM이 제안한 unified diff 초안

주 생성 주체:

- LLM
- 모듈: `patch_planner.py`

### `reports/patch-comparison.json`

경로 예시:

- [patch-comparison.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/patch-comparison.json)

생성 시점:

- LLM patch draft 이후
- simulation 이후 한 번 더 갱신 가능

의미:

- deterministic patch와 LLM patch의 차이
- simulation 결과
- 추천 source (`deterministic`, `llm`, `manual_review`)

주 생성 주체:

- deterministic 비교 로직
- 모듈: `patch_planner.py`

---

## 5. Runtime Merge Simulation

### `runtime/<site>/<run-id>/workspace/`

경로 예시:

- [workspace](/Users/junseok/Projects/SKN21-FINAL-5TEAM/runtime/food/food-run-308/workspace)

생성 시점:

- apply approval 이후

의미:

- 원본 복사본에 generated files와 patch를 반영해보는 실험 공간

주 생성 주체:

- deterministic
- 모듈: `runtime_runner.py`

### `reports/merge-simulation.json`

경로 예시:

- [merge-simulation.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/merge-simulation.json)

의미:

- deterministic patch apply 결과
- 성공/실패
- 실패한 patch artifact
- 적용 도구(`git apply`, `patch`) 관련 힌트

### `reports/llm-patch-simulation.json`

경로 예시:

- [llm-patch-simulation.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-patch-simulation.json)

의미:

- LLM patch를 별도 workspace에 적용해 본 결과

주 생성 주체:

- deterministic simulation
- 대상 patch만 다름
- 모듈: `runtime_runner.py`

---

## 6. 검증 단계

### `reports/backend-evaluation.json`

경로 예시:

- [backend-evaluation.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/backend-evaluation.json)

의미:

- Python compile
- framework entrypoint smoke

주 생성 주체:

- deterministic
- 모듈: `backend_evaluator.py`

### `reports/frontend-evaluation.json`

경로 예시:

- [frontend-evaluation.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/frontend-evaluation.json)

의미:

- frontend mount/build 관련 최소 평가

주 생성 주체:

- deterministic
- 모듈: `frontend_evaluator.py`

### `reports/smoke-results.json`

경로 예시:

- [smoke-results.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/smoke-results.json)

의미:

- smoke step별 raw 결과

### `reports/smoke-summary.json`

경로 예시:

- [smoke-summary.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/smoke-summary.json)

의미:

- smoke 결과 요약

### `reports/diagnostic-report.json`

경로 예시:

- [diagnostic-report.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/diagnostic-report.json)

의미:

- 검증 실패 시 root cause / retry 여부 / human review 필요 여부

주 생성 주체:

- Diagnostician role + deterministic report writer

---

## 7. Export 단계

### `reports/export-metadata.json`

경로 예시:

- [export-metadata.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/export-metadata.json)

의미:

- 최종 export source
- runtime patch export인지
- llm patch export인지

### `reports/approved.patch`

경로 예시:

- [approved.patch](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/approved.patch)

의미:

- 최종 승인된 patch 산출물

주 생성 주체:

- `recommended_source`에 따라 결정
- deterministic runtime export 또는 llm patch export

---

## 8. Debug / Observability Artifact

### `reports/execution-trace.jsonl`

경로 예시:

- [execution-trace.jsonl](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/execution-trace.jsonl)

의미:

- 단계별 타임라인
- 언제 어떤 단계가 시작/완료됐는지

### `reports/file-activity.json`

경로 예시:

- [file-activity.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/file-activity.json)

의미:

- 파일별 활동 로그
- 어떤 파일이 왜 선택됐는지

### `reports/llm-usage.json`

경로 예시:

- [llm-usage.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-usage.json)

의미:

- LLM 호출별 usage
- input/output/cached token
- 추정 비용

대표 component:

- `role:Analyzer`
- `role:Planner`
- `role:Generator`
- `role:Validator`
- `role:Diagnostician`
- `llm_codebase_interpretation`
- `llm_patch_proposal`
- `llm_patch_draft`

주 생성 주체:

- LLM 호출이 실제 발생한 시점마다 append
- 모듈: `debug_logging.py`, `role_runner.py`, `codebase_mapper.py`, `patch_planner.py`

---

## 에이전트별 관여 범위

### Analyzer

직접 관여 artifact:

- `llm-role-execution.json`
- `llm-debug/Analyzer.json`
- `llm-usage.json` 의 `role:Analyzer`

간접 영향 artifact:

- `patch-proposal.json`
- `patches/proposed.patch`

### Planner

직접 관여 artifact:

- `llm-role-execution.json`
- `llm-debug/Planner.json`
- `llm-usage.json` 의 `role:Planner`

간접 영향 artifact:

- `recommended_outputs`
- `patch-proposal.json`
- supporting file 목록

### Generator

직접 관여 artifact:

- `llm-role-execution.json`
- `llm-debug/Generator.json`
- `llm-usage.json` 의 `role:Generator`

간접 영향 artifact:

- `files/`
- `proposed.patch`
- `llm-proposed.patch`

### Validator

직접 관여 artifact:

- `llm-role-execution.json`
- `llm-debug/Validator.json`
- `llm-usage.json` 의 `role:Validator`

간접 영향 artifact:

- export approval 흐름

### Diagnostician

직접 관여 artifact:

- `llm-role-execution.json`
- `llm-debug/Diagnostician.json`
- `llm-usage.json` 의 `role:Diagnostician`
- `diagnostic-report.json`

---

## 해석 팁

### `llm-role-execution.json`과 `llm-codebase-interpretation.json`이 다를 수 있는 이유

가능하다.

예:

- `Analyzer` role은 `llm`
- `llm_codebase_interpretation`은 `fallback`

이는 서로 다른 LLM 호출이기 때문이다.

### `llm-debug`에 role 파일이 하나만 있을 수 있는 이유

가능하다.

예:

- 첫 실행은 `Analyzer`만 LLM
- 이후 resume는 deterministic

이 경우 `Analyzer.json`만 생긴다.

### Slack summary의 usage가 approval마다 같아 보일 수 있는 이유

같은 `run_id`로 resume하면서 새로운 LLM 호출이 없었다면, `llm-usage.json` totals가 그대로 유지된다.

즉 이는 "새 단계에서 LLM을 안 썼다"는 뜻일 가능성이 크다.

---

## 실무적으로 먼저 볼 파일

run이 이상할 때는 이 순서로 보는 것이 가장 빠르다.

1. [execution-trace.jsonl](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/execution-trace.jsonl)
2. [llm-role-execution.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-role-execution.json)
3. [llm-codebase-interpretation.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-codebase-interpretation.json)
4. [llm-debug](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-debug)
5. [llm-usage.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/llm-usage.json)
6. [patch-proposal.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/patch-proposal.json)
7. [merge-simulation.json](/Users/junseok/Projects/SKN21-FINAL-5TEAM/generated/food/food-run-308/reports/merge-simulation.json)

이 순서면 "어디서 deterministic으로 떨어졌는지", "어떤 파일이 실제 대상이었는지", "얼마나 토큰을 썼는지"를 빠르게 확인할 수 있다.
