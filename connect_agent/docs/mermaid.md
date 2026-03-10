flowchart TB
    O[`OrchestratorAgent`]

    subgraph A[탐색/분석 계층]
      SD[`SiteDiscoveryAgent`]
      SI[`SchemaInferenceAgent`]
      AC[`APIContractAgent`]
    end

    subgraph B[설계/연동 계층]
      TS[`ToolSpecBuilderAgent`]
      PG[`PolicyGuardAgent`]
      BC[`BackendConnectorAgent`]
    end

    subgraph C[RAG/데이터 계층]
      QI[`QnAIngestionAgent`]
      CS[`ChunkingStrategyAgent`]
      VI[`VectorIndexAgent`]
      QD[(Qdrant)]
      RDB[(RDB)]
    end

    subgraph D[검증/운영 계층]
      IT[`IntegrationTestAgent`]
      CE[`ConversationEvalAgent`]
      DO[`DeployOpsAgent`]
      HG[`HumanApprovalGate`]
    end

    O --> SD
    O --> SI
    O --> AC

    O --> TS
    O --> PG
    O --> BC

    O --> QI
    O --> CS
    O --> VI

    O --> IT
    O --> CE
    O --> DO
    O --> HG

    RDB --> QI --> CS --> VI --> QD
    AC --> TS --> BC
    PG --> BC
    BC --> IT
    VI --> CE
    IT --> O
    CE --> O

stateDiagram-v2
    [*] --> Discover
    Discover --> Design: contract/schema 확보
    Design --> Implement: tool/policy/chunk 결정
    Implement --> Validate: connector+rag 구성 완료
    Validate --> Release: 테스트 통과
    Validate --> Implement: 실패 시 수정 루프
    Release --> Monitor
    Monitor --> Discover: 신규 도메인 온보딩/변경 감지
    Monitor --> Implement: 핫픽스 필요

sequenceDiagram
    participant U as User/Admin
    participant O as Orchestrator
    participant AC as APIContract
    participant BC as BackendConnector
    participant QI as QnAIngestion
    participant CS as ChunkingStrategy
    participant VI as VectorIndex
    participant IT as IntegrationTest
    participant HG as HumanApprovalGate

    U->>O: 신규 사이트 연결 요청
    O->>AC: API/인증/엔드포인트 분석
    AC-->>O: capability map 반환

    O->>BC: tool 호출 코드 생성/연동
    BC-->>O: connector 준비 완료

    O->>QI: RDB QnA 추출
    QI->>CS: 문서 유형별 청킹 전략 적용
    CS->>VI: 임베딩/업서트
    VI-->>O: Qdrant 인덱스 준비 완료

    O->>IT: 통합 시나리오 테스트
    IT-->>O: pass/fail 리포트

    alt 고위험 액션 포함
      O->>HG: 환불/교환/취소 승인 요청
      HG-->>O: 승인
    end

    O-->>U: 연결 완료 + 검증 결과

graph LR
    P1[Phase 1 MVP]
    P2[Phase 2]
    P3[Phase 3]

    P1 --> P2 --> P3

    P1 --- O1[`OrchestratorAgent`]
    P1 --- A1[`APIContractAgent`]
    P1 --- B1[`BackendConnectorAgent`]
    P1 --- C1[`QnAIngestionAgent`]
    P1 --- C2[`VectorIndexAgent`]
    P1 --- D1[`IntegrationTestAgent`]

    P2 --- A2[`SchemaInferenceAgent`]
    P2 --- B2[`PolicyGuardAgent`]
    P2 --- C3[`ChunkingStrategyAgent`]

    P3 --- D2[`ConversationEvalAgent`]
    P3 --- D3[`DeployOpsAgent`]
    P3 --- M1[멀티 도메인 템플릿]