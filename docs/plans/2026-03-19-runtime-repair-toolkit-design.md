# Runtime Repair Toolkit Design

## Goal
runtime completion loop가 server boot/import/mount 오류를 만나면, 단순 분류에서 끝나지 않고 runtime workspace 안에서 안전한 자동 수정 도구를 사용해 재시도할 수 있게 한다.

## Problem
현재 runtime completion loop는 다음까지는 된다.

- backend/frontend boot 시도
- readiness/mount probe
- failure classification
- 일부 frontend repair

하지만 backend boot 계열은 아직 repair primitive가 거의 없다. 실제 `food-run-015`에서는 Django `urls.py`가 `from backend.chat_auth import chat_auth_token`를 import 하다가 `ModuleNotFoundError: No module named 'backend'`로 실패했는데:

- failure는 `backend_readiness_failed`로 분류됨
- recovery planner는 `repair_backend_entrypoint`를 제안함
- 실제 `_apply_repair_actions(...)`에는 해당 액션 구현이 없어 `repair_applied: false`로 종료됨

즉, “에이전트가 문제를 못 봤다”가 아니라 “문제를 고칠 수 있는 범용 repair tool이 부족하다”가 정확한 상태다.

## Recommended Approach
작은 범용 repair toolkit을 추가한다. 핵심은 자유형 LLM 수정이 아니라, trace/stderr에 기반한 deterministic repair 도구를 여러 개 두고 completion loop가 이를 조합하는 것이다.

권장 구성:

1. `traceback_signature_classifier`
- stderr/traceback를 읽고 더 구체적인 failure class를 만든다.
- 예: `backend_readiness_failed` -> `backend_import_resolution_failed`, `django_urlconf_import_failed`

2. `python_module_resolver`
- runtime workspace를 스캔해서 깨진 import가 실제 어떤 파일을 가리켜야 하는지 계산한다.
- 예: `backend.chat_auth`가 깨졌을 때 `workspace/backend/chat_auth.py`를 보고 `chat_auth` 또는 상대 import로 후보를 만든다.

3. `python_import_rewriter`
- 특정 파일의 import 문을 안전하게 rewrite한다.
- 예: `from backend.chat_auth import chat_auth_token` -> `from chat_auth import chat_auth_token`

4. `django_runtime_boot_repair`
- Django boot 실패를 대상으로 `urls.py`, `settings.py`, `wsgi/asgi`, app import 문제를 repair action으로 연결한다.
- 첫 구현 범위는 `urls.py` import resolution과 chat auth module wiring에 한정한다.

5. `frontend_module_resolver`
- CRA/Vite/Webpack 계열 import resolution 오류를 일반화해서 처리한다.
- 현재 `repair_shared_widget_import`를 더 구조화된 resolver 기반으로 흡수할 수 있다.

## Scope
이번 설계에서 우선 구현할 최소 범위:

- backend traceback를 읽어 `ModuleNotFoundError` / `ImportError` signature를 추출
- Django `urls.py` import mismatch를 runtime workspace 기준으로 rewrite
- broken module path가 실제 파일과 불일치할 때 보정
- `repair_backend_entrypoint`를 실제 구현으로 채우기
- frontend shared widget import recovery를 공통 resolver helper로 이동

이번 범위에서 제외:

- arbitrary Python AST refactor
- requirements install/env bootstrap 자동 수정
- browser-backed frontend self-healing 확대
- framework migration 수준 수정

## Data Flow
1. runtime completion runner가 stderr/traceback를 artifact에 남긴다.
2. failure classifier가 broad class 대신 richer signature를 만든다.
3. recovery planner가 signature에 맞는 repair action과 target file 후보를 제안한다.
4. orchestrator의 repair apply 단계가 toolkit helper를 호출한다.
5. helper는 runtime workspace만 수정한다.
6. completion loop가 재시도하고 성공하면 export patch로 수렴한다.

## Tool Responsibilities
### `traceback_signature_classifier`
- 입력: `probe_name`, `stdout`, `stderr`, optional `workspace`
- 출력:
  - `classification`
  - `exception_type`
  - `module_name`
  - `import_target`
  - `target_file`

### `python_module_resolver`
- 입력: `workspace_root`, `module_name`
- 출력:
  - candidate file paths
  - preferred import path from caller file context

### `python_import_rewriter`
- 입력: `file_path`, `broken_import`, `replacement_import`
- 동작:
  - line-based minimal rewrite
  - exact replacement only
  - no broad formatting changes

### `django_runtime_boot_repair`
- 입력: traceback classification + runtime workspace
- 동작:
  - locate broken urlconf/import file
  - resolve module against runtime tree
  - rewrite import
  - emit repair evidence for attempts artifact

## Failure Classes To Add
- `backend_import_resolution_failed`
- `django_urlconf_import_failed`
- `backend_module_symbol_missing`
- `frontend_import_resolution_failed`

`backend_readiness_failed`는 umbrella class로 남기되, richer signatures가 있으면 그것을 우선 사용한다.

## Success Criteria
- `ModuleNotFoundError: No module named 'backend'` 같은 Django runtime import 오류를 completion loop가 자동 보정한다.
- `repair_backend_entrypoint`가 `repair_applied: true`가 될 수 있다.
- runtime workspace 수정 후 second attempt에서 readiness가 회복되면 export patch가 갱신된다.
- toolkit helper는 source tree나 generated tree를 직접 수정하지 않는다.

## Risks
- 잘못된 import rewrite는 런타임을 더 망가뜨릴 수 있다.
- module resolution이 너무 공격적이면 다른 package 구조를 깨뜨릴 수 있다.

완화:
- exact traceback 기반으로만 동작
- target file 존재 확인 후에만 rewrite
- 첫 구현은 `chat_auth`, `urls.py`, runtime-local module mismatch`에 제한

## Recommendation
우선순위는 다음 순서가 맞다.

1. traceback 기반 backend import failure 세분화
2. module resolver + import rewriter 추가
3. `repair_backend_entrypoint` 구현
4. 기존 frontend shared widget recovery를 공통 resolver 패턴으로 정리

이 순서면 `food-run-015` 같은 실제 실패를 바로 자동 복구할 수 있다.
