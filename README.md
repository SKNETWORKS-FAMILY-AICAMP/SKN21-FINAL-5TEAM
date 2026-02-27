# MOYEO (모여)

**LLM 기반 대화형 이커머스 플랫폼**

SK Networks Family AI Camp - Team 5 | End-to-End Full Stack Implementation

> 기존 이커머스의 복잡한 필터링 및 키워드 검색 한계를 넘어,
> 자연어 기반 의도 파악 및 개인화된 쇼핑 경험을 제공합니다.

## 기술 스택

| 분야         | 기술                                           |
| ------------ | ---------------------------------------------- |
| **AI Core**  | LangGraph, LangChain, OpenAI API, RAG          |
| **Backend**  | Python 3.13, FastAPI, SQLAlchemy               |
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS |
| **Database** | MySQL 8.0 (관계형), Qdrant (벡터)              |
| **DevOps**   | Docker, Docker Compose, Nginx, AWS             |

## 프로젝트 구조

```
AI Core (RAG & LangGraph) → Backend (API & DB Modeling) → Frontend (Streaming UI) → DevOps (AWS & Security)
```

---

## [The Brain] AI 에이전트

### 데이터 전략: Context Injection

원본 데이터(무신사 FAQ, 전자상거래 표준약관)를 전처리 엔진을 통해 벡터 검색에 최적화된 데이터로 변환합니다.

- **비식별화**: 플랫폼 명칭 제거
- **UI 용어 삭제**: 불필요한 UI 텍스트 정리
- **Context Enrichment**: 상위 조항 제목을 본문에 결합하여 문맥이 주입된 데이터 청크 생성

### 검색 아키텍처: Hybrid Search

Dense Vector(의미 기반)와 Sparse Vector(키워드 매칭)를 결합한 하이브리드 검색을 수행합니다.

```
사용자 질의
    ├── Dense Vector (Qdrant) → 의미 기반 검색
    └── Sparse Vector (BM25)  → 키워드 매칭
              ↓
      Qdrant Vector DB (Hybrid Search)
              ↓
      Reranking (ms-marco-MiniLM-L-12-v2)
              ↓
        Retrieved Result
```

### AI 에이전트 코어: LangGraph 흐름 제어

```
User Input
    ↓
Intent Classification (NLU)
    ↓
┌──────────────────────────────────────────────────────────────┐
│ 정보 요청 │ 주문 조회 │ 반품 신청 │ 규정 문의 │ 결제 변경 │ ... │
└──────────────────────────┬───────────────────────────────────┘
                           ↓
                  Slot Filling Needed?
                   ├── Yes → 정보 요청 질문 생성 (루프)
                   └── No  → Action Execution
```

- **Dynamic Context Loading**: 사용자 DB에서 VIP 등급, 최근 주문(Last 3) 등을 Pre-fetching
- **지원 인텐트**: 주문 조회, 반품 신청, 규정 문의, 결제 변경, 리뷰 작성, 상품 검색, 재고 확인

### 품질 검증: Synthetic Data

GPT-5-mini 기반 합성 데이터 생성 및 검증 결과:

| Test Scenarios         | 지표            | 결과 |
| ---------------------- | --------------- | ---- |
| **Single-turn** (단순) | Intent Coverage | 100% |
| **Multi-turn** (문맥)  | Tool Coverage   | 100% |
| **Edge Case** (예외)   | Balance Score   | >0.7 |

---

## [The Skeleton] 백엔드 & 데이터베이스

### 데이터베이스 모델링: 3NF 정규화

MySQL 8.0 + SQLAlchemy ORM 기반, IE 표기법 준수

```
Users ──┬── Orders ──── Payments
        │       └──── OrderItems ──── InventoryTransactions
        ├── Carts
        └── UserHistory
```

### 데이터 무결성 및 보안 전략

| 전략               | 구현                   | 설명                                      |
| ------------------ | ---------------------- | ----------------------------------------- |
| **Cascade Delete** | `on_delete='CASCADE'`  | 부모 데이터 삭제 시 자식 데이터 자동 정리 |
| **Constraints**    | `CHECK (price > 0)`    | 가격, 수량 등 논리적 오류 DB 차단         |
| **Soft Delete**    | `deleted_at: DATETIME` | 데이터 영구 삭제 방지 및 이력 보존        |

### 커머스 비즈니스 로직: 주문 상태 머신

```
Order Created → Payment Complete → Preparing → Shipping → Delivered
├─── 즉시 취소 가능 ────────────┤    ├── 취소 불가 (반품 절차 안내) ──┤
                                                                    ↓
                                                             Return Request
                                                          ├── 단순변심 (배송비 차감)
                                                          └── 파손 (전액 환불)
```

- **WISMO** (Where Is My Order) Tracking Logic 지원

---

## [The Face] 프론트엔드

### 스트리밍 및 리치 UI

- **Token Streaming (SSE)**: 실시간 응답 스트리밍
- **Rich UI Rendering**: 상품 카드, 주문 목록 등 구조화된 UI 컴포넌트

### 확장성: Google Workspace 생태계 연동

- Chrome Extension API + Google OAuth 2.0
- Landing Page → Google 로그인 Popup → Google Docs Side Panel 연동

---

## [The Nervous System] 인프라 & 안정성

### 서빙 아키텍처

```
HTTPS/SSL Traffic → AWS Cloud (VPC)
                       └── EC2 Instance
                            ├── FastAPI + Gunicorn/Uvicorn Workers
                            ├── RDS (MySQL) — Main Transactional DB
                            └── Vector DB (Qdrant)
```

### 시스템 안정성 및 Human-in-the-Loop

- **AI Triage**: 요청을 AI 자동 처리 또는 상담원 연결(Agent Escalation)로 분기
  - Negative Sentiment 감지 시 상담원 연결
- **Session Persistence**: DB Snapshot 기반 세션 유지
- **API Rate Limiting**: Throttle 기반 과부하 방지

---

## 프로젝트 요약

데이터 수집부터 서비스 서빙까지 완전한 엔드투엔드 구현

- Data Pipeline & Hybrid Search
- Context-Aware AI Agent
- 3NF Normalized Database
- Secure AWS Deployment
