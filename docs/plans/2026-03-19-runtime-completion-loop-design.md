# Runtime Completion Loop Design

## Goal
onboarding generation과 export가 끝난 뒤에도 runtime workspace를 실제 실행 상태까지 끌고 가서, chatbot mount 완료 여부를 검증하고 실패 시 runtime workspace 기준으로 자동 복구를 반복한 뒤 최종 patch export로 수렴시키는 opt-in 자동화 루프를 추가한다.

## Problem
현재 onboarding 파이프라인은 아래까지만 자동화한다.

- runtime workspace 준비
- generated overlay merge simulation
- frontend/backend evaluator
- smoke validation
- export

이 구조는 artifact 생성과 정적/빌드 검증에는 유용하지만, 실제 runtime 디렉토리에서 서버를 켜고 chatbot이 mount되는지까지는 보장하지 못한다.

지금 드러난 실제 실패는 이 경계에서 발생한다.

- generation은 성공
- runtime frontend build 시 alias/import mismatch로 실패
- 이 실패는 export 이후 실제 서버 실행 단계에서야 명확히 드러남

즉, 현재 파이프라인에는 `export 이후 실제 실행 환경에서 완성 여부를 확인하고, 실패를 runtime workspace에 반영하면서 수리하는 후속 loop`가 없다.

## Recommended Approach
`runtime completion loop`를 새 opt-in 단계로 추가한다.

- 기본값은 비활성화
- CLI 플래그로만 활성화
- 적용 범위는 `runtime/<site>/<run-id>/workspace`에 한정
- 성공 시 runtime 변경분을 다시 export patch로 수렴
- 실패 시 diagnostic/recovery artifact를 남기고 human review로 종료

핵심은 기존 evaluator와 recovery 체인을 버리지 않고, 그 위에 실제 프로세스 실행과 mount probe를 붙이는 것이다.

## Placement In Pipeline
새 loop는 `export approval 승인 후 patch export 직전`이 아니라, `기존 export 완료 직후`에 붙인다.

이렇게 두는 이유:

- 기존 artifact lifecycle을 깨지 않음
- 현재 export 결과를 baseline으로 유지 가능
- completion loop가 runtime workspace를 추가 수정한 경우 마지막에 export artifact를 한 번 더 갱신 가능

최종 흐름은 다음과 같다.

1. generation/apply/validation/export 기존 흐름 실행
2. `--enable-runtime-completion-loop`가 켜진 경우 completion loop 진입
3. runtime workspace에서 backend/frontend 서버 기동
4. HTTP readiness + mount probe 수행
5. 실패 시 recovery planner로 repair action 생성
6. repair action을 runtime workspace에만 적용
7. probe 재실행
8. 성공 시 runtime diff를 다시 export patch로 반영
9. 실패 누적 시 human review로 종료

## Completion Runner Contract
새 `runtime_completion_runner.py`를 도입한다.

책임:

- runtime workspace 기준 실행 계획 수립
- backend/frontend 서버 프로세스 기동/종료
- readiness probe 실행
- mount probe 실행
- failure classification 입력 정규화
- repair attempt 결과 누적
- 최종 completion report 작성

입력:

- `run_root`
- `runtime_workspace`
- `site`
- `run_id`
- optional `terminal_logger`
- retry budget / timeout / opt-in flags

출력:

- `passed`
- `attempt_count`
- `backend_probe`
- `frontend_probe`
- `mount_probe`
- `failure_reason`
- `repair_actions_applied`
- `report_path`

## Runtime Probe Strategy
### Backend
기존 analysis/evaluator 결과를 재사용해 backend 실행 후보를 결정한다.

우선순위:

- Django: `manage.py runserver`
- FastAPI: `uvicorn ...`
- Flask: app module 실행

성공 기준:

- auth/chat endpoint readiness probe 응답
- 최소 하나의 chat 관련 endpoint가 기대 status 반환

### Frontend
frontend root의 package manager와 scripts를 감지한다.

우선순위:

- `npm|yarn|pnpm install`
- `dev` script가 있으면 dev server 기동
- 없으면 `build` 후 preview/start 후보 실행

성공 기준:

- frontend HTTP 응답 가능
- mount target page 접근 가능

### Mount Probe
SPA 환경에서는 단순 HTML fetch만으로 mount 완료를 확인할 수 없다. 따라서 probe를 두 단계로 나눈다.

1. `lightweight probe`
- frontend page 응답 확인
- mount target source에 `SharedChatbotWidget` wiring이 존재하는지 확인
- build/runtime JS error를 stdout/stderr에서 수집

2. `browser-backed probe`
- 가능하면 Python Playwright 기반으로 실제 페이지를 열어 DOM에서 `data-chatbot-status`를 확인
- `loading`, `authenticated`, `unauthenticated`, `error` 중 하나가 렌더되면 mount 성공으로 본다

환경에 browser-backed probe 실행 기반이 없으면:

- 상태를 `unsupported_environment`로 기록
- lightweight probe만으로 성공 판정을 내리지 않음
- human review 또는 fallback policy로 넘긴다

## Repair Model
자동 복구는 `runtime workspace`에만 적용한다.

허용:

- alias/import path 수정
- frontend widget wrapper 교체
- frontend mount patch 보정
- backend route wiring/entrypoint 보정
- env/bootstrap script 보정

비허용:

- source tree 직접 수정
- generated root를 중간 단계에서 직접 덮어쓰기
- evidence 없는 framework 전환

복구 성공 후에만 마지막 단계에서 export patch를 다시 생성한다.

## Recovery Integration
기존 `build_recovery_plan`, `failure_classifier`, `_apply_repair_actions`를 확장한다.

새 failure class 예시:

- `frontend_import_resolution_failed`
- `frontend_dev_server_boot_failed`
- `backend_server_boot_failed`
- `chatbot_mount_missing`
- `chatbot_status_not_rendered`
- `mount_probe_environment_unsupported`

repair action 예시:

- `repair_shared_widget_import`
- `repair_frontend_mount_target`
- `repair_frontend_dev_bootstrap`
- `repair_backend_entrypoint`

## Artifacts
새 artifact:

- `reports/runtime-completion.json`
- `reports/runtime-completion-attempts.json`
- `reports/runtime-server-probes.json`
- `reports/runtime-mount-probe.json`

기존 재사용:

- `reports/backend-evaluation.json`
- `reports/frontend-evaluation.json`
- `reports/diagnostic-report.json`
- `reports/recovery-plan.json`
- `reports/export-metadata.json`

## Success Criteria
- `--enable-runtime-completion-loop`가 켜지면 export 이후 loop가 자동 실행된다.
- backend auth/chat endpoint readiness probe가 통과한다.
- frontend 서버가 실제로 기동한다.
- mount target page probe가 통과한다.
- browser-backed probe가 가능한 환경에서는 DOM에서 `data-chatbot-status`를 확인한다.
- repair가 runtime workspace에만 적용되고, 최종 결과는 export patch로 수렴한다.
- retry budget 초과 또는 non-repairable failure는 human review로 일관되게 종료된다.

## Non-Goals
- full conversational E2E 기본화
- visual diff testing
- 무제한 self-healing loop
- source tree 직접 자동 수정

## Assumptions
- completion loop는 opt-in 플래그가 있을 때만 실행한다.
- runtime workspace가 repair 대상의 단일 진실원이다.
- browser-backed mount probe는 환경 지원 시에만 강제한다.
- baseline 성공 기준은 backend readiness + frontend boot + mount probe 통과다.
