# Evaluation Dataset System

평가 데이터셋 자동 생성 및 평가 시스템

## 🎯 개요

챗봇의 성능을 체계적으로 평가하기 위한 자동화된 데이터셋 생성 및 평가 프레임워크입니다.

- **자동 생성**: 템플릿 + 실제 DB 데이터 기반 시나리오 자동 생성
- **다양성 확보**: 7가지 변형 타입으로 입력 다양성 확보
- **보안 테스트**: 5가지 공격 유형 체계적 테스트
- **품질 관리**: 중복/다양성/커버리지 자동 체크
- **자동 평가**: Intent/Entity/Tool/Response 다차원 평가

## 📁 구조

```
benchmark/
├── build_dataset.py              # 데이터셋 생성 메인 실행
├── evaluation_dataset/
│   ├── templates/
│   │   ├── intent_templates.json      # 9개 Intent 템플릿
│   │   ├── entity_variations.json     # 15+ Entity 패턴
│   │   └── conversation_flows.json    # 13개 대화 시나리오
│   └── generator/
│       ├── scenario_generator.py      # 기능 테스트 시나리오
│       ├── variation_generator.py     # 입력 변형 생성
│       └── adversarial_generator.py   # 보안 테스트 생성
├── evaluator/
│   ├── evaluator.py                   # 평가 실행기
│   └── metrics.py                     # 평가 지표
└── quality_tools/
    └── quality_checker.py             # 품질 체크
```

## 🚀 사용법

### 1. 데이터셋 생성

```bash
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM

# 전체 데이터셋 자동 생성
python -m chatbot.benchmark.build_dataset

# 생성 결과:
# - functional_20240115_120000.jsonl (기능 테스트)
# - conversation_20240115_120000.jsonl (대화 흐름)
# - security_20240115_120000.jsonl (보안 테스트)
```

**생성되는 데이터셋 구성:**
- 기능 테스트: 17개 도구 × 30샘플 × 3변형 = ~1,530개
- 대화 흐름: 20개 시나리오 (멀티턴)
- 보안 테스트: 5개 공격유형 × 10샘플 = 50개

### 2. 품질 체크

```bash
# 중복/다양성/커버리지 검증
python -m chatbot.benchmark.quality_tools.quality_checker \
  --dataset ecommerce/chatbot/benchmark/datasets/functional_20240115_120000.jsonl \
  --output quality_report.json

# 출력 예시:
# 품질: GOOD
# 중복률: 0.5%
# 균형도: 0.85
# Intent 커버리지: 100%
```

### 3. 평가 실행

```bash
# 챗봇 성능 평가
python -m chatbot.benchmark.evaluator.evaluator \
  --dataset ecommerce/chatbot/benchmark/datasets/functional_20240115_120000.jsonl \
  --output evaluation_results.json

# 출력 예시:
# 📊 1530개 샘플 평가 시작...
# ✅ Pass Rate: 87.5%
# ✅ Intent Accuracy: 0.92
# ✅ Overall Score: 0.85
```

## 📊 데이터셋 상세

### Intent 커버리지 (9개)
```
order_inquiry      - 주문 조회 (배송 상태, 주문 상세)
order_modification - 주문 수정 (주소 변경, 취소)
product_search     - 상품 검색 (카테고리, 가격)
faq_inquiry        - FAQ 조회 (반품, 배송)
terms_inquiry      - 약관 조회 (개인정보, 이용약관)
address_management - 주소 관리 (등록, 수정, 삭제)
cart_management    - 장바구니 관리
payment_inquiry    - 결제 문의
general_greeting   - 일반 인사
```

### Tool 커버리지 (17개)

**주문 관리 (6개)**
- `get_order_list`, `get_order_detail`, `modify_shipping_address`
- `request_order_cancel`, `request_order_return`, `request_order_exchange`

**정보 검색 (4개)**
- `search_products_by_keyword`, `get_product_by_id`
- `search_faq`, `search_terms`

**주소 관리 (3개)**
- `get_shipping_addresses`, `add_shipping_address`, `modify_shipping_address_tool`

**기타 (4개)**
- `get_cart_items`, `pay_order`, `check_delivery_status`, `fallback_tool`

### 변형 타입 (7개)
```
formal       - 공식적 표현 ("주문 내역을 조회해주세요")
informal     - 비공식적 표현 ("주문 좀 봐줘")
typo         - 오타 포함 ("주몬 내역")
abbreviation - 축약어 ("주문 조회ㄱㄱ")
verbose      - 장황한 표현 ("저 이번에 주문한 것 있는데...")
casual       - 구어체 ("주문 어디갔어?")
paraphrase   - 의역 ("내가 산 거 어디있니?")
```

### 보안 테스트 (5개 유형)
```
prompt_injection        - 프롬프트 주입 공격
jailbreak              - 역할 탈출 시도
authorization_bypass   - 권한 우회 시도
pii_extraction         - 개인정보 유출 시도
malicious_input        - 악의적 입력 (SQL, XSS)
```

## 🔍 평가 지표

### 1. Intent Accuracy
```python
exact_match = predicted_intent == expected_intent
intent_f1 = macro_average_across_intents()
```

### 2. Entity Extraction Score
```python
{
  "type_precision": 0.92,  # 타입 정확도
  "type_recall": 0.88,
  "type_f1": 0.90,
  "value_accuracy": 0.85,  # 값 정확도
  "exact_match": 0.80      # 완전 일치
}
```

### 3. Tool Selection Accuracy
```python
# 멀티툴 시나리오 지원
predicted_tools = {"get_order_list", "get_order_detail"}
expected_tools = {"get_order_list"}
precision = len(overlap) / len(predicted)
recall = len(overlap) / len(expected)
```

### 4. Response Quality
```python
{
  "completeness": check_required_info(),
  "semantic_similarity": difflib.SequenceMatcher(),
  "response_length": len(response)
}
```

### 5. Security Score
```python
checks = [
  "no_system_prompt_leak",
  "no_code_execution",
  "no_sql_injection",
  "no_unauthorized_access",
  "maintains_role",
  "rejects_inappropriate"
]
security_score = passed / total
```

## ⚙️ 커스터마이징

### 생성 설정 변경

```python
from chatbot.benchmark.build_dataset import DatasetBuilder

builder = DatasetBuilder(db_session)

# 커스텀 설정
custom_config = {
    "functional": {
        "enabled": True,
        "samples_per_tool": 50  # 도구당 50개 샘플
    },
    "conversation": {
        "enabled": True,
        "multi_turn_scenarios": 30  # 30개 대화 시나리오
    },
    "security": {
        "enabled": True,
        "attack_samples": 100  # 100개 보안 테스트
    },
    "variations": {
        "enabled": True,
        "per_sample": 5  # 샘플당 5개 변형
    }
}

generated = builder.generate_full_dataset(config=custom_config)
```

### 템플릿 추가

**intent_templates.json:**
```json
{
  "new_intent": {
    "description": "신규 Intent 설명",
    "tools": ["tool_name"],
    "templates": [
      "{action}해주세요",
      "{action} 가능할까요?"
    ],
    "entities": {
      "entity_name": ["value1", "value2"]
    }
  }
}
```

## 📈 워크플로우

```
1. 템플릿 정의 (templates/*.json)
   ↓
2. 실제 DB 데이터 로드 (Order, Product, User)
   ↓
3. 시나리오 생성 (scenario_generator.py)
   - 단일턴 시나리오
   - 멀티턴 대화
   - 도구 커버리지
   - 엣지 케이스
   ↓
4. 변형 생성 (variation_generator.py)
   - 7가지 타입 변형
   - LLM 기반 paraphrase
   ↓
5. 보안 테스트 생성 (adversarial_generator.py)
   - 5가지 공격 유형
   ↓
6. 품질 체크 (quality_checker.py)
   - 중복 제거
   - 다양성 검증
   - 커버리지 확인
   ↓
7. 평가 실행 (evaluator.py)
   - 챗봇 API 호출
   - 다차원 평가
   - 결과 리포트
```

## 🎓 Best Practices

### 1. 데이터 품질 우선
- 양보다 질: 500개 고품질 > 2000개 저품질
- 중복률 10% 이하 유지
- 균형도 0.7 이상 목표

### 2. 커버리지 확보
- 모든 Intent: 최소 30개 샘플
- 모든 Tool: 최소 15개 시나리오
- 엣지 케이스: 전체의 10%

### 3. 실제 데이터 활용
- DB에서 실제 order_number 사용
- 실제 product.name 활용
- 실제 shipping_address 패턴

### 4. 정기적 업데이트
- 주 1회: 실사용 로그 기반 추가
- 월 1회: 전체 재생성 및 평가
- 분기 1회: 템플릿 업데이트

## 🔗 관련 문서

- [LOGGING_GUIDE.md](./LOGGING_GUIDE.md) - 실사용 로그 수집
- [CRAWLING_GUIDE.md](../CRAWLING_GUIDE.md) - 데이터 수집

## 📞 트러블슈팅

**Q: 생성 속도가 느림**
```python
# LLM 호출 줄이기
config["variations"]["enabled"] = False  # 변형 비활성화
config["security"]["attack_samples"] = 20  # 보안 테스트 축소
```

**Q: 품질이 낮음**
```bash
# 품질 리포트 확인
python -m chatbot.benchmark.quality_tools.quality_checker \
  --dataset path/to/dataset.jsonl

# 중복 제거 후 재생성
```

**Q: 커버리지 부족**
```python
# samples_per_tool 증가
config["functional"]["samples_per_tool"] = 50
```
