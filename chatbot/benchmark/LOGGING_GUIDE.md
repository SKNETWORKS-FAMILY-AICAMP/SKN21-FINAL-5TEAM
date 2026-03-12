# 실사용 로그 기반 데이터셋 구축 가이드

## 📋 개요

실제 사용자 대화 로그에서 고품질 학습/평가 데이터셋을 자동으로 추출하는 시스템입니다.

---

## 🏗️ 시스템 아키텍처

```
┌─────────────────┐
│  User Request   │
└────────┬────────┘
         │
         v
┌─────────────────────────────────┐
│   Chat API + Logging Middleware │  ← 자동 로그 수집
└────────┬────────────────────────┘
         │
         v
┌──────────────────────┐
│  Database (MySQL)    │
│  - conversations     │  ← 세션 정보
│  - messages          │  ← 개별 메시지
│  - tool_calls        │  ← 도구 호출
│  - quality_metrics   │  ← 품질 점수 (자동 계산)
└────────┬─────────────┘
         │
         v
┌──────────────────────────────┐
│  Dataset Extractor Script    │  ← 스마트 필터링
│  - 품질 점수 기반 선별        │
│  - 다양성 샘플링              │
│  - Train/Eval/Val 분할        │
└────────┬─────────────────────┘
         │
         v
┌──────────────────────┐
│  Final Dataset       │
│  - training.jsonl    │  ← 학습용
│  - evaluation.jsonl  │  ← 평가용
│  - validation.jsonl  │  ← 검증용
└──────────────────────┘
```

---

## 🎯 핵심 필터링 로직

### **1. 품질 점수 자동 계산 (Quality Score)**

모든 대화는 0.0~1.0 사이의 품질 점수를 자동으로 받습니다.

```python
품질 점수 = (
    0.30 × 도구_호출_성공률 +      # 기능 정확성
    0.20 × (1 - 오류율) +          # 안정성
    0.15 × 멀티턴_복잡도 +         # 시나리오 복잡도
    0.20 × 사용자_만족도 +         # 실제 만족도
    0.15 × 응답_속도_점수          # 성능
)
```

**품질 레이블 자동 할당:**
- **EXCELLENT (0.8+)**: 학습 데이터 우선 선택
- **GOOD (0.6-0.8)**: 평가 데이터 후보
- **FAIR (0.4-0.6)**: 사람이 리뷰 필요
- **POOR (<0.4)**: 제외

### **2. 의미있는 순간 포착 기준**

❌ **제외되는 대화:**
- 1턴만 있고 이탈한 경우
- 오류율 > 50%
- 도구 호출이 모두 실패
- 테스트/스팸 대화

✅ **선택되는 대화:**
```python
meaningful_criteria = {
    "quality_score": >= 0.6,
    "has_successful_tool_call": True,
    "error_rate": < 0.5,
    "turn_count": >= 2,
    "status": "completed" or "error_recovered"
}
```

### **3. 다양성 샘플링**

단순히 고품질만 선택하면 편향 발생 → 균형 있게 샘플링

```python
# Intent별 균등 분배
intent_distribution = {
    "order_lookup": 25%,
    "cancel_order": 20%,
    "knowledge_search": 20%,
    "return_exchange": 15%,
    ...
}

# 도구별 최소 샘플 보장
tool_minimum = {
    "cancel_order": 30개,  # 중요 도구
    "get_order_status": 30개,
    "search_knowledge_base": 40개,
    ...
}
```

---

## 🚀 사용 방법

### **Step 1: 데이터베이스 마이그레이션**

```bash
# 로그 테이블 생성
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM

# 모델 임포트 추가 (필요시)
# ecommerce/platform/backend/app/main.py에 추가:
# from ecommerce.backend.app.router.chatbot_logs.models import *

# Alembic 마이그레이션 (또는 직접 테이블 생성)
python -c "
from ecommerce.backend.app.database import engine, Base
from ecommerce.backend.app.router.chatbot_logs.models import *
Base.metadata.create_all(bind=engine)
print('✅ 로그 테이블 생성 완료')
"
```

### **Step 2: API에 로깅 통합**

```python
# ecommerce/chatbot/src/api/v1/endpoints/chat.py 수정

from ecommerce.backend.app.router.chatbot_logs.middleware import log_chat_interaction

@router.post("/chat")
async def chat_endpoint(request: ChatRequest, current_user: User = Depends(get_current_user)):
    start_time = time.time()
    session_id = request.previous_state.get("session_id") or f"session_{uuid.uuid4().hex[:16]}"
    
    try:
        result = graph_app.invoke(state)
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        # ✅ 로그 저장
        log_chat_interaction(
            session_id=session_id,
            user_id=current_user.id,
            user_message=request.message,
            assistant_response=get_final_response(result),
            graph_state=result,
            execution_time_ms=execution_time_ms
        )
        
        return ChatResponse(...)
    except Exception as e:
        log_chat_interaction(
            session_id=session_id,
            user_id=current_user.id,
            user_message=request.message,
            assistant_response=None,
            graph_state={"error": str(e)},
            execution_time_ms=int((time.time() - start_time) * 1000)
        )
        raise
```

### **Step 3: 로그 수집 (서비스 운영)**

```bash
# 서비스가 실행되면 자동으로 로그가 쌓입니다
# - 모든 대화가 DB에 저장
# - 품질 점수 자동 계산
# - 의도, 엔티티, 도구 호출 메타데이터 기록

# 현재 로그 상태 확인
python -c "
from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.router.chatbot_logs.service import LogService

db = SessionLocal()
service = LogService(db)

# 품질 분포 확인
print('품질 분포:', service.get_quality_distribution())

# 도구 사용 통계
print('도구 통계:', service.get_tool_usage_stats())

db.close()
"
```

### **Step 4: 데이터셋 추출**

```bash
# 최근 30일 데이터에서 500개 샘플 추출
cd /Users/junseok/Projects/SKN21-FINAL-5TEAM

python ecommerce/chatbot/src/data_preprocessing/extract_dataset_from_logs.py \
    --days 30 \
    --count 500 \
    --output ecommerce/chatbot/data/extracted_datasets

# 출력 예시:
# 📊 데이터셋 추출 시작 (최근 30일)
# 1️⃣  의미있는 세션 필터링...
#    ✓ 342개 세션 발견
# 2️⃣  다양성 기반 샘플링...
#    ✓ 500개 세션 선택
# 3️⃣  데이터셋 분할...
#    ✓ Train: 350
#    ✓ Eval: 100
#    ✓ Val: 50
# 4️⃣  샘플 추출...
# ✅ 추출 완료!
#    📈 총 샘플: 1247
#    - Training: 873
#    - Evaluation: 249
#    - Validation: 125
#
# 💾 Training: ecommerce/chatbot/data/extracted_datasets/training_20260220_143022.jsonl
# 💾 Evaluation: ecommerce/chatbot/data/extracted_datasets/evaluation_20260220_143022.jsonl
# 💾 Validation: ecommerce/chatbot/data/extracted_datasets/validation_20260220_143022.jsonl
# 📊 Stats: ecommerce/chatbot/data/extracted_datasets/stats_20260220_143022.json
```

### **Step 5: 추출된 데이터 확인**

```python
# 샘플 확인
import json

with open('ecommerce/chatbot/data/extracted_datasets/training_20260220_143022.jsonl') as f:
    for i, line in enumerate(f):
        if i >= 3:  # 처음 3개만
            break
        sample = json.loads(line)
        print(f"\n샘플 {i+1}:")
        print(f"  입력: {sample['input_text']}")
        print(f"  의도: {sample.get('intent')}")
        print(f"  도구: {sample.get('tool_name')}")
        print(f"  유형: {sample.get('sample_type')}")

# 출력 예시:
# 샘플 1:
#   입력: 주문번호 ORD-20240115-001 취소해줘
#   의도: cancel_order
#   도구: cancel_order
#   유형: single_turn
#
# 샘플 2:
#   입력: 배송비는 얼마야?
#   의도: knowledge_search
#   도구: search_knowledge_base
#   유형: single_turn
#
# 샘플 3:
#   입력: 내 주문 목록 보여줘
#   의도: order_lookup
#   도구: get_order_list
#   유형: tool_call
```

---

## 📊 데이터 분석 및 모니터링

### **품질 분포 확인**

```python
from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.router.chatbot_logs.service import LogService

db = SessionLocal()
service = LogService(db)

# 품질 레이블 분포
distribution = service.get_quality_distribution()
print(distribution)
# {'excellent': 45, 'good': 123, 'fair': 78, 'poor': 34, 'unlabeled': 5}

# 도구 사용 통계
tool_stats = service.get_tool_usage_stats()
for stat in tool_stats:
    print(f"{stat['tool_name']}: {stat['success_rate']:.1%} 성공률")
# cancel_order: 95.2% 성공률
# get_order_status: 98.7% 성공률
# search_knowledge_base: 87.3% 성공률

# Intent 분포
intent_dist = service.get_intent_distribution()
print(intent_dist)
# {'order_lookup': 156, 'cancel_order': 89, 'knowledge_search': 134, ...}

db.close()
```

### **특정 조건 데이터 추출**

```python
# 특정 도구 사용 케이스만 추출
cancel_sessions = service.get_sessions_by_tool(
    tool_name="cancel_order",
    execution_status="success",
    min_quality_score=0.7,
    limit=50
)

# 멀티턴 대화만 추출
multi_turn = service.get_multi_turn_conversations(
    min_turns=4,
    min_quality_score=0.6,
    limit=50
)

# 엣지 케이스 (오류 복구 케이스)
edge_cases = service.get_edge_cases(limit=30)
```

---

## 🎓 베스트 프랙티스

### **1. 지속적 데이터 수집**

```bash
# Cron Job으로 주기적 추출 (매주 일요일 새벽 3시)
0 3 * * 0 cd /Users/junseok/Projects/SKN21-FINAL-5TEAM && \
    python ecommerce/chatbot/src/data_preprocessing/extract_dataset_from_logs.py \
    --days 7 --count 100 --output ecommerce/chatbot/data/weekly_datasets
```

### **2. 품질 모니터링 대시보드**

```python
# 주간 품질 리포트 생성
def generate_weekly_report():
    db = SessionLocal()
    service = LogService(db)
    
    # 지난 7일 통계
    cutoff = datetime.utcnow() - timedelta(days=7)
    
    sessions = db.query(ConversationSession).filter(
        ConversationSession.created_at >= cutoff
    ).all()
    
    report = {
        "total_sessions": len(sessions),
        "avg_quality_score": sum(s.quality_score or 0 for s in sessions) / len(sessions),
        "excellent_ratio": len([s for s in sessions if s.quality_label == QualityLabel.EXCELLENT]) / len(sessions),
        "avg_turns": sum(s.turn_count for s in sessions) / len(sessions),
        "tool_success_rate": len([s for s in sessions if s.has_successful_tool_call]) / len(sessions)
    }
    
    print(f"주간 리포트 ({datetime.now().strftime('%Y-%m-%d')})")
    print(f"  총 대화: {report['total_sessions']}")
    print(f"  평균 품질: {report['avg_quality_score']:.2f}")
    print(f"  우수 비율: {report['excellent_ratio']:.1%}")
    print(f"  평균 턴수: {report['avg_turns']:.1f}")
    print(f"  도구 성공률: {report['tool_success_rate']:.1%}")
    
    db.close()
```

### **3. 사용자 피드백 통합**

```python
# 만족도 조사 API 추가
@router.post("/feedback")
async def submit_feedback(
    session_id: str,
    satisfaction: int,  # 1-5
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()
    service = LogService(db)
    
    service.end_session(
        session_id=session_id,
        status=ConversationStatus.COMPLETED,
        user_satisfaction=satisfaction
    )
    
    db.close()
    return {"status": "success"}

# 프론트엔드에서 대화 종료 시 만족도 물어보기:
# "도움이 되셨나요? ⭐⭐⭐⭐⭐"
```

### **4. 데이터 품질 개선 사이클**

```
1. 로그 수집 (1주일)
   ↓
2. 품질 분석
   - 낮은 품질 패턴 파악
   - 자주 실패하는 도구 식별
   ↓
3. 모델/프롬프트 개선
   ↓
4. 다시 로그 수집
   ↓
5. 품질 개선 확인
```

---

## 💡 고급 활용

### **특정 시나리오 집중 수집**

```python
# A/B 테스트용 태그 추가
log_chat_interaction(
    ...,
    graph_state={
        ...,
        "tags": {
            "experiment": "prompt_v2",
            "variant": "A"
        }
    }
)

# 나중에 태그별 분석
sessions_with_tag = db.query(ConversationSession).filter(
    ConversationSession.tags["experiment"].astext == "prompt_v2"
).all()
```

### **실시간 품질 알림**

```python
# 품질 점수가 낮은 세션 발생 시 알림
def check_quality_alert(session: ConversationSession):
    if session.quality_score < 0.3:
        send_alert(f"저품질 대화 발생: {session.session_id}, 점수: {session.quality_score}")
```

---

## 📌 요약

**핵심 원칙:**
1. ✅ 모든 대화를 로그하되, 품질 점수로 자동 필터링
2. ✅ 다양성을 유지하며 샘플링 (편향 방지)
3. ✅ 지속적으로 수집하고 주기적으로 데이터셋 업데이트
4. ✅ 사용자 피드백을 통합하여 품질 개선

**효과:**
- 🎯 수동 레이블링 최소화 (80% 자동화)
- 📈 실제 사용 패턴 반영
- 🔄 지속적 품질 개선 사이클
- 💰 비용 절감 (크라우드소싱 불필요)
