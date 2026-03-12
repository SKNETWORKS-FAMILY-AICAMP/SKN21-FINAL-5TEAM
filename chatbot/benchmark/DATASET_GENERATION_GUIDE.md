# 평가 합성데이터 생성 가이드

## 1. 챗봇 평가 합성데이터 (AI-Generated Test Dataset)

챗봇 시스템은 다양한 사용자 발화와 시나리오에 대해 정확히 응답해야 하지만, 실제 사용자 로그가 축적되기 전에는 **품질 검증이 불가능**합니다. 따라서 **합성데이터(Synthetic Data)** 를 통해 사전에 기능/대화/예외 상황을 체계적으로 테스트해야 합니다.

### 1) 데이터 목적 및 출처

- **목적**: LangGraph 기반 챗봇의 NLU(의도 분류), Tool Calling, 대화 흐름 검증
- **생성 방식**:
  - 템플릿 기반 변형 (intent_templates.json)
  - GPT-5-mini 자동 생성 (누락된 도구 커버리지 보충)
  - 실제 DB 데이터 주입 (Order, Product, User 테이블)
- **출력 형식**: JSONL (Line-delimited JSON)
- **파일 구조**:
  ```
  datasets/
    ├── functional_YYYYMMDD_HHMMSS.jsonl    # 기능 테스트 (단일턴)
    ├── conversation_YYYYMMDD_HHMMSS.jsonl  # 대화 테스트 (멀티턴)
    └── edge_case_YYYYMMDD_HHMMSS.jsonl     # 엣지 케이스
  ```

### 2) 데이터 형태 및 구조

#### 단일턴 시나리오 (Functional Test)

```json
{
  "input": "주문번호 ORD-20260220-001 취소해줘",
  "intent": "cancel_order",
  "expected_tool": "cancel_order",
  "expected_output": {
    "intent": "cancel_order",
    "tools": ["cancel_order"]
  },
  "metadata": {
    "type": "single_turn",
    "template": "{order_id} 취소해줘",
    "use_real_data": true
  }
}
```

**핵심 필드**:

- `input`: 사용자 발화 (템플릿 + 실제 데이터 치환)
- `intent`: NLU 분류 목표 (9개 타입)
- `expected_tool`: 호출되어야 할 LangChain 도구 (15개 도구)
- `metadata.use_real_data`: 실제 DB 데이터 사용 여부

#### 멀티턴 시나리오 (Conversation Test)

```json
{
  "flow_name": "order_cancel_flow",
  "description": "주문 취소 전체 플로우",
  "turns": [
    {
      "user": "주문 취소하고 싶어요",
      "intent": "cancel_order",
      "expected_tool": "get_order_list",
      "context_required": []
    },
    {
      "user": "ORD-20260220-001 취소해주세요",
      "intent": "cancel_order",
      "expected_tool": "cancel_order",
      "context_required": ["order_id"]
    }
  ],
  "complexity": "medium"
}
```

**핵심 특징**:

- `turns`: 대화 턴별 검증 포인트
- `context_required`: 이전 턴에서 수집해야 할 정보
- `complexity`: 난이도 (simple/medium/hard)

#### 엣지 케이스 (Edge Case Test)

```json
{
  "input": "주문번호 INVALID-999 취소해줘",
  "intent": "cancel_order",
  "expected_error": "order_not_found",
  "metadata": {
    "type": "edge_case",
    "category": "invalid_data",
    "difficulty": "hard"
  }
}
```

### 3) 생성 시 유의할 점 (핵심 로직)

합성데이터 품질은 **커버리지(Coverage)** 와 **다양성(Diversity)** 에 달려 있습니다. 코드(`build_dataset.py`, `scenario_generator.py`)는 다음 기법들을 사용합니다.

#### ① 도구 커버리지 보장 (Tool Coverage Enforcement)

**문제점**:

- 15개 LangChain 도구 중 13개는 템플릿이 없어 테스트 불가능
- 수동으로 모든 도구의 테스트 케이스를 작성하는 것은 비효율적

**해결책**:

```python
# build_dataset.py
def _discover_all_tools() -> set[str]:
    """nodes_v2.py의 TOOLS를 자동 검색"""
    from chatbot.src.graph.nodes_v2 import TOOLS
    return {tool.name for tool in TOOLS if isinstance(tool.name, str)}
```

- **Single Source of Truth**: `nodes_v2.TOOLS`에서 모든 도구 목록 자동 추출
- **누락 감지**: `intent_templates.json`에 없는 도구는 GPT로 자동 템플릿 생성
- **품질 검증**: `QualityChecker`가 `tool_coverage` 메트릭으로 검증

#### ② GPT 기반 템플릿 자동 생성 (Auto Template Generation)

**문제점**:

- `change_product_option`, `check_refund_eligibility` 등 13개 도구는 템플릿 부재
- 도구가 추가될 때마다 수동으로 예시 문장 작성 필요

**해결책**:

```python
# scenario_generator.py
def _auto_generate_tool_template(self, tool_name: str):
    """GPT-5-mini로 도구 설명 기반 템플릿 자동 생성"""
    prompt = f"""
    도구 이름: {tool_name}
    설명: {tool_description}
    파라미터: {tool_args}

    한국어로 자연스러운 사용자 질문 5개 생성
    """
    # GPT 호출 → {"examples": [...], "tools": [...]}
    # intent_templates.json에 저장 (캐싱)
```

**변환 예시**:

- **도구**: `change_product_option(order_id, option_id)`
- **GPT 생성**:
  - "주문한 상품 옵션 바꾸고 싶어요"
  - "사이즈 변경 가능한가요?"
  - "색상을 검정색으로 바꿔주세요"
  - "배송 전이라면 옵션 수정할 수 있죠?"
  - "주문번호 ORD-001 상품 변경"

**핵심**: 도구의 메타데이터(이름, 설명, 파라미터)만으로 자연스러운 사용자 발화 생성

#### ③ 실제 데이터 주입 (Real Data Injection)

**문제점**:

- 하드코딩된 주문번호(`ORD-001`)는 DB에 없어 실제 테스트 불가능
- 상품명이 "테스트 상품"이면 검색 결과 없음

**해결책**:

```python
def _cache_real_data(self):
    """실제 DB 데이터 캐싱"""
    self.real_orders = self.db.query(Order).limit(100).all()
    self.real_products = self.db.query(Product).limit(50).all()

def _fill_entities(self, template: str, use_real_data: bool):
    """템플릿 엔티티를 실제 데이터로 치환"""
    if "{order_id}" in template and use_real_data:
        order = random.choice(self.real_orders)
        template = template.replace("{order_id}", order.order_number)
```

**변환 예시**:

- **템플릿**: `"{order_id} 취소해줘"`
- **치환 후**: `"ORD-20260220-073 취소해줘"` (실제 DB 주문)

**핵심**: 테스트 데이터가 실제 시스템에서 **실행 가능(Executable)** 해야 함

#### ④ 표현 다양성 확보 (Expression Diversity with LLM)

**문제점**:

- 템플릿 기반만으로는 표현이 획일적 ("주문 취소해줘"만 반복)
- 실제 사용자는 존댓말/반말, 오타, 줄임말을 혼용

**해결책**:

```python
def _generate_variations_with_llm(self, template: str, num_variations=3):
    """하나의 템플릿을 3가지 다른 표현으로 변형"""
    prompt = f"""
    템플릿: {template}

    요구사항:
    1. 격식체/반말 혼용
    2. 오타나 줄임말 포함 가능
    3. 의도는 동일하게 유지
    """
    # GPT-5-mini로 변형 생성 (temperature=0.9)
```

**변환 예시**:

- **원본**: "주문 취소해줘"
- **변형1**: "주문 취소하고 싶은데요"
- **변형2**: "츄소 가능?"
- **변형3**: "이거 취소할 수 있나요"

**핵심**: 동일 의도에 대해 **언어적 다양성** 확보

#### ⑤ 품질 검증 (Quality Metrics)

생성된 데이터셋은 자동으로 품질 검증을 받습니다:

```python
# quality_checker.py
quality_report = analyze_dataset(
    data=dataset,
    required_intents=REQUIRED_INTENTS,  # 9개 인텐트
    required_tools=REQUIRED_TOOLS        # 15개 도구
)
```

**검증 메트릭**:

1. **중복률 (Duplicate Rate)**: < 10%
   - 동일한 발화가 반복되면 과적합 위험
2. **균형도 (Balance Score)**: > 0.7
   - 특정 인텐트에 편중되지 않도록 분포 균형
3. **인텐트 커버리지 (Intent Coverage)**: 100%
   - 9개 필수 인텐트 모두 포함 여부
4. **도구 커버리지 (Tool Coverage)**: 100%
   - 15개 도구가 모두 테스트되는지 확인

**최종 판정**:

```
✅ EXCELLENT: 모든 지표 우수
⚠️  GOOD: 일부 지표 개선 필요
❌ POOR: 데이터셋 재생성 권장
```

### 4) 전처리 파이프라인 흐름

```
┌─────────────────────────────────────────────────────────┐
│ 1. 도구 자동 발견 (nodes_v2.TOOLS)                      │
│    → 15개 LangChain 도구 추출                            │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 2. 템플릿 매칭 (intent_templates.json)                  │
│    → 있으면: 기존 템플릿 사용                            │
│    → 없으면: GPT 자동 생성 + 파일 저장                   │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 3. 실제 데이터 주입 (DB Query)                          │
│    → Order/Product/User 랜덤 샘플링                      │
│    → {order_id}, {product_name} 치환                    │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 4. LLM 변형 생성 (GPT-5-mini, temp=0.9)               │
│    → 1개 템플릿 → 3개 변형 (다양성 확보)                 │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 5. JSONL 저장 + 품질 검증                               │
│    → QualityChecker 자동 실행                           │
│    → 중복률/균형도/커버리지 리포트                        │
└─────────────────────────────────────────────────────────┘
```

### 5) 핵심 파일 구조

```
benchmark/
├── build_dataset.py                    # 메인 오케스트레이터
│   ├── _discover_all_tools()           # 도구 자동 발견
│   ├── REQUIRED_INTENTS                # 9개 인텐트 정의
│   └── generate_full_dataset()         # 전체 생성 로직
│
├── evaluation_dataset/
│   ├── generator/
│   │   └── scenario_generator.py       # 시나리오 생성기
│   │       ├── _cache_real_data()      # DB 데이터 캐싱
│   │       ├── _fill_entities()        # 실제 데이터 치환
│   │       ├── _generate_variations_with_llm()  # LLM 변형
│   │       ├── _auto_generate_tool_template()  # GPT 템플릿 생성
│   │       └── generate_tool_coverage_scenarios()  # 도구 커버리지
│   │
│   └── templates/
│       ├── intent_templates.json       # 인텐트별 예시 문장
│       ├── entity_variations.json      # 엔티티 변형 패턴
│       └── conversation_flows.json     # 멀티턴 대화 플로우
│
├── quality_tools/
│   └── quality_checker.py              # 품질 검증
│       ├── calculate_duplicate_rate()
│       ├── calculate_balance_score()
│       └── analyze_dataset()           # 종합 리포트
│
└── datasets/                           # 생성된 JSONL
    ├── functional_*.jsonl
    ├── conversation_*.jsonl
    └── edge_case_*.jsonl
```

### 6) 실행 방법

```bash
# 전체 데이터셋 생성
uv run python -m chatbot.benchmark.build_dataset

# 품질 리포트만 확인
uv run python -m chatbot.benchmark.quality_tools.quality_checker \
    --dataset datasets/functional_20260220_125006.jsonl
```

### 7) 주요 설정값 (build_dataset.py)

```python
config = {
    "functional": {
        "samples_per_tool": 20,        # 도구당 20개 샘플
        "variation_count": 3,          # 템플릿당 3가지 변형
        "use_real_data": True          # 실제 DB 데이터 사용
    },
    "conversation": {
        "samples_per_flow": 10,        # 플로우당 10개 대화
        "max_turns": 5                 # 최대 5턴
    },
    "edge_case": {
        "total_samples": 50            # 엣지 케이스 50개
    }
}
```

### 8) 품질 보증 기준

| 메트릭              | 목표  | 측정 방법               |
| ------------------- | ----- | ----------------------- |
| **중복률**          | < 10% | 동일 발화 비율          |
| **균형도**          | > 0.7 | Intent 분포의 Gini 계수 |
| **Intent Coverage** | 100%  | 9개 인텐트 포함 여부    |
| **Tool Coverage**   | 100%  | 15개 도구 포함 여부     |
| **변형 다양성**     | > 70% | 유니크 토큰 비율        |

---

## 핵심 요약

| 항목            | 법률 데이터 전처리                 | 평가 합성데이터 생성                     |
| --------------- | ---------------------------------- | ---------------------------------------- |
| **핵심 과제**   | 문맥 보존 (Context Preservation)   | 커버리지 보장 (Coverage Enforcement)     |
| **주요 기법**   | Context Injection (조항 제목 주입) | Auto Template Generation (GPT 자동 생성) |
| **데이터 특성** | 계층 구조 (조/항/호)               | 의도-도구 매핑 (Intent-Tool Mapping)     |
| **검증 방식**   | 검색 정확도 (Retrieval Accuracy)   | 품질 메트릭 (Duplicate/Balance/Coverage) |
| **자동화 수준** | 반자동 (파싱 룰 필요)              | 완전 자동 (GPT + DB 연동)                |

**공통점**: 두 시스템 모두 **"단순 텍스트 저장"이 아닌 "검색 가능한 형태로 구조화"**하는 것이 핵심입니다.
