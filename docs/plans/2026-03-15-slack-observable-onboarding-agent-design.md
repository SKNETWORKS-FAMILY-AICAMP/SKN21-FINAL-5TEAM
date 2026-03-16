# Slack-Observable Onboarding Agent Design

## Goal

범용 웹사이트 온보딩을 목표로 하는 SaaS 챗봇 연동 에이전트를 설계한다. 이 에이전트는 원본 사이트 코드를 직접 수정하지 않고, 분석부터 생성, 검증, export까지 진행하며, 그 과정에서 orchestrator와 역할별 subagent의 판단을 Slack thread에서 사람이 관찰하고 필요한 승인만 수행할 수 있어야 한다.

## Why

현재 onboarding MVP는 `food`, `bilyeo`, `ecommerce`에서 관찰한 패턴을 바탕으로 한 rule-based scaffold 수준이다. 이 구조는 프로토타입으로는 유효하지만, 범용 웹사이트 온보딩에는 한계가 명확하다.

필요한 것은 아래를 동시에 만족하는 구조다.

- 어떤 사이트가 들어와도 분석과 생성 흐름을 일반화할 수 있어야 한다.
- LLM 판단은 활용하되, 실행과 판정은 deterministic layer가 통제해야 한다.
- 사람은 Slack에서 각 agent의 판단 근거를 읽고 중요한 승인만 할 수 있어야 한다.
- 원본 사이트는 항상 보존되어야 한다.

## Core Decision

초기 구조는 `단일 orchestrator + 역할별 프롬프트`로 간다.

- 실제 실행 엔진은 하나다.
- 단계별로 `Analyzer`, `Planner`, `Generator`, `Validator`, `Diagnostician` 역할 프롬프트를 바꿔 호출한다.
- Slack에는 각 역할이 독립 agent처럼 구조화된 메시지를 남긴다.

이 방식은 내부 복잡도를 통제하면서도, 외부에서는 멀티에이전트 협업처럼 관찰할 수 있다.

## Agent Topology

초기 역할은 아래 5개로 고정한다.

1. `Analyzer`
   - 코드베이스를 읽고 인증, 상품, 주문, 프론트 삽입 후보를 탐지
   - 근거와 함께 구조화된 분석 결과 반환

2. `Planner`
   - 분석 결과를 capability 단위로 매핑
   - 어떤 생성물이 필요한지와 우선순위 결정

3. `Generator`
   - overlay files, patches, smoke steps 초안 생성
   - capability별 patch 전략 제안

4. `Validator`
   - overlay 적용, smoke test, 정적 검증 결과 평가
   - 성공/실패 판정과 위험 요약 작성

5. `Diagnostician`
   - 실패 로그 해석
   - 다음 재시도 방향과 수정 제안 생성

## State Machine

orchestrator 상태는 아래로 고정한다.

```text
queued
-> analyzing
-> planning
-> generating
-> awaiting_apply_approval
-> applying
-> validating
-> diagnosing
-> awaiting_export_approval
-> exporting
-> completed
```

보조 종료 상태:

- `human_review_required`
- `failed`
- `rejected`

상태 전이 규칙:

- 분석 실패 시 `diagnosing`
- 생성 실패 시 `diagnosing`
- 검증 실패 시 `diagnosing`
- `diagnosing`은 retry budget 안에서 `planning` 또는 `generating`으로 되돌릴 수 있음
- budget 초과 또는 high-risk 판정이면 `human_review_required`

## Approval Gates

사람 승인 지점은 최소 3개로 제한한다.

1. `analysis_approval`
   - 사이트 구조 해석이 맞는지 확인
   - 잘못된 분석으로 downstream이 모두 틀어지는 것을 방지

2. `apply_approval`
   - 생성된 overlay/patch를 runtime 복사본에 적용하기 직전
   - 고위험 patch를 사람이 확인

3. `export_approval`
   - 최종 patch/PR 생성 직전
   - 승인된 결과만 실제 반영 후보로 승격

그 외 단계는 자동 진행한다.

## Slack Thread Protocol

run 하나당 Slack thread 하나를 사용한다.

상위 채널:

- 예: `#onboarding-runs`
- thread root는 orchestrator가 생성

thread root 메시지 필드:

- `run_id`
- `site`
- `source_root`
- `goal`
- `current_state`
- `approval_status`

모든 후속 agent 메시지는 같은 thread에만 게시한다.

## Slack Message Schema

각 agent 메시지는 자유로운 대화가 아니라 구조화된 판단 로그 형식으로 올린다.

필수 필드:

- `role`
- `claim`
- `evidence`
- `confidence`
- `risk`
- `next_action`
- `blocking_issue`

예시:

```text
[Analyzer]
Claim: 이 사이트는 Flask session 기반 인증으로 보입니다.
Evidence:
- routes/auth.py 에서 session["user_id"] 저장
- order route 에 login_required 데코레이터 사용
Confidence: 0.91
Risk: medium
Next action: session 기반 chat auth endpoint 초안 생성 계획으로 전달
Blocking issue: none
```

승인 요청 메시지는 별도 스키마를 사용한다.

- `approval_type`
- `summary`
- `recommended_option`
- `risk_if_approved`
- `risk_if_rejected`
- `available_actions`

## Deterministic vs LLM Responsibilities

### Deterministic Layer

하드코딩으로 유지할 항목:

- orchestrator 상태머신
- 승인 게이트 규칙
- retry budget
- event schema
- Slack thread/run mapping
- tool 실행기
- patch apply
- smoke/test 실행
- 결과 수집 및 판정 규칙
- overlay/manifest/export 포맷

### LLM Layer

LLM에게 맡길 항목:

- 코드 구조 해석
- capability 추론
- patch 초안 생성
- 실패 원인 설명
- 수정 방향 제안
- 위험 요약

### Hybrid Layer

혼합 구조:

- analyzer tool이 코드 증거를 수집
- LLM이 그 증거를 해석
- orchestrator가 그 결과를 상태머신과 검증 규칙에 반영

원칙:

- 실행과 판정은 deterministic layer
- 해석과 제안은 LLM

## Capability Model

범용성을 위해 site name 기반 분기 대신 capability 기반으로 움직인다.

초기 capability:

- `auth.login_state_detection`
- `auth.chat_token_issue`
- `catalog.product_list`
- `catalog.product_detail`
- `orders.list`
- `orders.detail`
- `orders.action`
- `frontend.widget_mount`

Planner는 사이트를 위 capability 집합으로 표현하고, Generator는 capability별 template/patch 전략을 선택한다.

## Event Model

모든 단계는 이벤트를 남긴다.

기본 이벤트 타입:

- `run.created`
- `analysis.completed`
- `analysis.approval_requested`
- `plan.completed`
- `generation.completed`
- `apply.approval_requested`
- `apply.completed`
- `validation.completed`
- `diagnosis.completed`
- `export.approval_requested`
- `export.completed`
- `run.failed`
- `run.completed`

이벤트는 Slack bridge와 audit log 둘 다로 전달한다.

## Retry Strategy

retry는 무제한으로 두지 않는다.

기본 정책:

- 동일 run에서 최대 3회 재시도
- 동일 failure signature가 2회 반복되면 사람 검토 요청
- security/auth 관련 high-risk 실패는 즉시 `human_review_required`

Diagnostician은 매 실패마다 아래를 반환해야 한다.

- `failure_summary`
- `root_cause_hypothesis`
- `proposed_fix`
- `confidence`
- `should_retry`

## Human Interaction Model

사람은 Slack에서 아래만 결정한다.

- 분석 승인
- 적용 승인
- export 승인
- 중단
- 재시도 강제

나머지는 orchestrator가 자동 진행한다.

사람이 Slack에서 확인해야 하는 핵심은 아래다.

- agent의 claim이 근거와 일치하는지
- 승인 시 리스크가 허용 가능한지
- 반복 실패가 구조적 문제인지

## Non-Goals

이번 설계의 비목표:

- 완전한 자율 배포
- 실시간 양방향 자연어 대화형 agent 군집
- 무제한 self-healing loop
- 모든 프레임워크를 즉시 지원하는 범용 patch generator

## Next Step

다음 구현은 아래 순서가 적절하다.

1. run/event/state schema 정의
2. Slack bridge 인터페이스 정의
3. 역할별 message contract 정의
4. orchestrator 상태머신 구현
5. analyzer/planner/generator/validator/diagnostician role runner 구현
6. approval gate 처리
7. 기존 onboarding MVP와 연결
