# 온보딩 V2 5분 발표 운영안

## 목적

이 문서는 온보딩 시스템을 처음 듣는 사람에게 `5분 이하`로 설명할 때,

- 어떤 순서로 말해야 이해가 빠른지
- 어떤 슬라이드를 쓰면 되는지
- 어떤 문장은 꼭 말해야 하는지

를 바로 사용할 수 있게 정리한 발표 가이드다.

핵심 원칙은 하나다.

`stage 이름보다 문제와 연결 관계를 먼저 설명한다.`

---

## 추천 발표 순서

### 0. 0:00 ~ 0:30

문제부터 시작한다.

- 쇼핑몰마다 로그인 구조, 주문 API, 프론트 mount 지점이 다르다.
- 그래서 챗봇을 붙이는 작업이 매번 수작업이었다.

추천 멘트:

> 이 시스템은 서로 다른 쇼핑몰 코드를 챗봇 서버에 자동 연결해주는 온보딩 엔진입니다.

이 구간에서는 `analysis`, `planning`, `compile` 같은 내부 용어를 먼저 꺼내지 않는다.

### 1. 0:30 ~ 1:40

구성도를 보여준다.

사용 슬라이드:

- `presentation/slides2/14.html`

설명 순서:

1. `Onmo UI`가 시작 버튼과 진행 상황을 담당한다.
2. 실제 generation은 `run_onboarding_generation --engine v2`가 담당한다.
3. 대상은 `Host source repo`와 `Chatbot repo/server` 두 코드베이스다.
4. 실행은 원본이 아니라 `Runtime workspace`에서 먼저 일어난다.
5. retrieval은 `Qdrant`, 생성/추론은 `LLM/OpenAI`를 쓴다.
6. 마지막에는 `host patch`, `chatbot patch`, `validation evidence`, `indexed retrieval`이 남는다.

연결 멘트:

> 즉, 이 시스템은 한 파일 생성기가 아니라 여러 서버와 저장소를 엮어서 온보딩 결과를 만들어내는 실행 엔진입니다.

### 2. 1:40 ~ 3:20

버튼을 눌렀을 때의 generation 흐름을 말한다.

사용 슬라이드:

- `presentation/slides2/15.html`

설명 순서:

1. `analysis`: 인증, 주문, 프론트 mount 지점, retrieval source를 찾는다.
2. `planning`: 어떤 계약으로 연결할지 integration plan을 만든다.
3. `compile`: 수정안을 하나로 만들지 않고 host/chatbot edit program으로 분리한다.
4. `apply`: 원본을 고치지 않고 runtime workspace에 먼저 적용한다.
5. `compile preflight`: chatbot import 문제를 validation 전에 빨리 잡는다.
6. `export`: runtime 결과를 다시 host/chatbot patch로 뽑는다.
7. `indexing / validation`: Qdrant 인덱싱과 실제 런타임 검증을 수행한다.

강조 멘트:

> LLM이 바로 소스를 덮어쓰는 게 아니라, 계약을 확인하고 격리된 실행 환경에서 먼저 검증한 뒤 패치만 뽑아냅니다.

### 3. 3:20 ~ 4:10

runtime과 retrieval을 설명한다.

같은 슬라이드 `15.html`의 하단 왼쪽 패널을 사용한다.

설명 순서:

1. 사용자는 `widget`에서 요청을 보낸다.
2. `chatbot API`가 요청을 받고 LangGraph로 넘긴다.
3. 질문 성격에 따라 `order`, `policy`, `discovery` subagent로 간다.
4. 정책/FAQ/이미지 검색이 필요하면 `Qdrant`를 조회한다.
5. 이미지 검색은 우선 `CLIP + Qdrant`를 쓰고, 실패하면 `Vision -> text retrieval`로 fallback한다.

강조 멘트:

> retrieval은 부가 기능처럼 보이지만, 인덱싱이 성공해야 capability profile이 올라가고 이미지 업로드 같은 기능이 실제로 활성화됩니다.

### 4. 4:10 ~ 4:50

repair를 설명한다.

같은 슬라이드 `15.html`의 하단 오른쪽 패널을 사용한다.

설명 순서:

1. 실패가 나면 `failure bundle`로 정리한다.
2. 원인을 진단한다.
3. `effective rewind`를 계산한다.
4. 필요한 stage부터만 다시 실행한다.

강조 멘트:

> 실패했다고 처음부터 다시 돌리지 않습니다. repair LLM이 rewind 후보를 내더라도, 최종 rewind는 엔진이 deterministic하게 결정합니다.

### 5. 4:50 ~ 5:00

마무리는 결과와 정체성으로 끝낸다.

추천 멘트:

> 즉 이 시스템은 코드 생성기가 아니라, 분석, 계약 정의, 패치 생성, 실행 검증, 복구까지 포함한 온보딩 실행 엔진입니다.

---

## 꼭 말해야 하는 설계 포인트

### 1. Contract-first

- `/widget.js`
- `/api/chat/auth-token`
- generated adapter interface

이런 안정된 연결 계약을 먼저 잡고, 각 사이트를 그 계약에 맞춘다.

### 2. Dual-patch

- host patch
- chatbot patch

를 분리하는 이유는 두 코드베이스의 책임이 다르기 때문이다.

### 3. Isolated runtime

원본 코드를 바로 고치지 않고 runtime workspace에서 먼저 적용한다.

이 포인트를 말해야 청중이 `왜 바로 patch하지 않느냐`를 이해한다.

### 4. Early-fail

compile preflight로 import/구조 문제를 validation 전에 앞당겨 잡는다.

### 5. LLM 보조, 엔진 통제

LLM이 분석과 repair에 참여하지만,

- verified contract
- allowlist
- replay
- effective rewind

같은 마지막 통제권은 deterministic 코드가 가진다.

### 6. Generated adapter

새 사이트 전용 예외 로직을 따로 늘리는 대신, 기존 chatbot tool/adapter 체계에 들어오는 generated adapter를 만든다.

이 포인트를 말하면 “단순 패치 생성”이 아니라 “기존 런타임 계약에 편입”시키는 설계라는 점이 전달된다.

---

## 슬라이드 사용법

### 메인 2장

- `presentation/slides2/14.html`
- `presentation/slides2/15.html`

### 깊게 물어보면 이어서 보여줄 슬라이드

- `presentation/slides2/7.html`
  - Qdrant, CLIP, retrieval 구조를 더 자세히 설명할 때
- `presentation/slides2/8.html`
  - 온보딩 파이프라인을 더 세분화해서 설명할 때
- `presentation/slides2/9.html`
  - 운영 관점, 승인 게이트, recovery/resume 흐름을 부연할 때

---

## 리허설 체크리스트

발표 후 청중이 아래 네 가지를 답할 수 있어야 한다.

1. 왜 host patch와 chatbot patch를 나누는가
2. 왜 원본이 아니라 runtime workspace에서 먼저 적용하는가
3. Qdrant 이미지 검색이 generation 이후 어떻게 활성화되는가
4. repair가 전체 재시작이 아니라 stage rewind라는 점

이 네 가지가 약하면 서버 이름이나 파일 경로 설명을 줄이고,

`문제 -> 연결 -> 검증 -> 복구`

메시지를 더 앞세우는 편이 낫다.

---

## 발표자가 기억할 한 문장

> 온보딩 V2는 쇼핑몰 코드와 챗봇 서버를 자동으로 연결하되, 바로 덮어쓰지 않고 계약 확인, 격리 실행, 검증, repair까지 거쳐 최종 patch를 내보내는 실행 엔진이다.
