import re
import json
from typing import List, Optional, Dict, Any
from langchain_core.messages import AIMessage
from langsmith import traceable
from qdrant_client import models
from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.schemas.nlu import NLUResult, IntentType, ActionType
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings
# 신규 프롬프트 및 도구 임포트
from ecommerce.chatbot.src.prompts.system_prompts import (
    ECOMMERCE_SYSTEM_PROMPT, 
    NLU_SYSTEM_PROMPT, 
    GENERATION_SYSTEM_PROMPT_TEMPLATE,
    CATEGORY_KEYWORDS_MAP,
    QUERY_REWRITE_PROMPT
)
from ecommerce.chatbot.src.tools.order_tools import (
    get_shipping_details, 
    update_payment_method, 
    check_cancellation,
    cancel_order,
    check_return_eligibility,
    register_return_request,
    get_order_details,
    get_user_orders
)
from ecommerce.chatbot.src.tools.service_tools import register_gift_card, get_reviews, create_review

# Advanced Retrieval: Hybrid Search + Reranking Dependencies
from fastembed import SparseTextEmbedding
from flashrank import Ranker, RerankRequest

# Initialize models globally (Load once)
print("Loading Retrieval Models...")
SPARSE_MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
# FlashRank is lightweight (ONNX) but better cached
RANKER = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank_cache")
print("Retrieval Models Loaded.")

@traceable(run_type="retriever", name="Retrieve Documents")
def retrieve(state: AgentState):
    """
    Retrieve documents from Qdrant.
    [통합 검색] 카테고리 필터 검색과 전체 검색 결과를 병합하여 최적의 문서를 찾습니다.
    (Hybrid Search + Reranking applied)
    """
    # Advanced Retrieval: Hybrid Search + Reranking (Models are global)
    
    client = get_qdrant_client()
    openai = get_openai_client()
    
    question = state["question"]
    category = state.get("category")

    # 1. 질문 임베딩 생성 (Dense & Sparse)
    # Dense
    emb_response = openai.embeddings.create(
        input=question,
        model=settings.EMBEDDING_MODEL
    )
    query_dense_vector = emb_response.data[0].embedding
    
    # Sparse
    query_sparse_vector = list(SPARSE_MODEL.embed([question]))[0]
    query_sparse_indices = query_sparse_vector.indices.tolist()
    query_sparse_values = query_sparse_vector.values.tolist()

    # 2. 검색 전략 실행 (Hybrid Search)
    collections = [settings.COLLECTION_FAQ, settings.COLLECTION_TERMS]
    candidates = []

    for col in collections:
        # 필터 설정
        query_filter = None
        if category:
            if col == settings.COLLECTION_FAQ:
                field_name = "main_category"
                mapped_category = "취소/교환/반품" if category == "취소/반품/교환" else category
            else: # COLLECTION_TERMS
                field_name = "category"
                if category == "회원 정보": mapped_category = "회원"
                elif category == "주문/결제": mapped_category = "구매/결제"
                else: mapped_category = category
            
            query_filter = models.Filter(
                must=[models.FieldCondition(key=field_name, match=models.MatchValue(value=mapped_category))]
            )

        try:
            prefetch = [
                models.Prefetch(
                    query=query_dense_vector,
                    using="", # Default dense vector
                    filter=query_filter,
                    limit=20,
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=query_sparse_indices, values=query_sparse_values),
                    using="text-sparse",
                    filter=query_filter,
                    limit=20,
                ),
            ]
            
            results = client.query_points(
                collection_name=col,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF), # Reciprocal Rank Fusion
                limit=20, # Fetch top 20 candidates for reranking
            ).points
            
            for hit in results:
                # Add collection context to payload for reranker/LLM
                hit.payload["_collection"] = col
                candidates.append(hit)
                
        except Exception as e:
            print(f"Error searching {col}: {e}")

    # 3. Reranking using FlashRank
    if not candidates:
        return {"documents": [], "is_relevant": False}
        
    # Deduplicate candidates by ID (if any overlap between collections, though unlikely with UUIDs)
    unique_candidates = {c.id: c for c in candidates}.values()
    
    passages = []
    for c in unique_candidates:
        # Construct text for reranker
        text_content = (
            c.payload.get('question', '') + " " + c.payload.get('answer', '') if c.payload.get('question') else
            c.payload.get('text', '') or 
            c.payload.get('content', '') or 
            c.payload.get('title', '')
        ).strip()
        
        passages.append({
            "id": c.id,
            "text": text_content,
            "meta": c.payload
        })
        
    rerank_request = RerankRequest(query=question, passages=passages)
    reranked_results = RANKER.rerank(rerank_request)
    
    # 4. Top 5 Selection
    top_results = reranked_results[:5]
    
    all_documents = []
    for res in top_results:
        payload = res["meta"]
        score = res["score"]
        
        doc_type = "정보"
        if 'main_category' in payload: doc_type = "FAQ"
        elif 'category' in payload: doc_type = "약관"
        
        content_text = res["text"]
        all_documents.append(f"[{doc_type}] {content_text}")
        print(f"Verified Doc ({score:.4f}): {content_text[:30]}...")

    print(f"최종 Reranking 후 문서 수: {len(all_documents)}")
    
    return {
        "documents": all_documents,
        "is_relevant": len(all_documents) > 0
    }

@traceable(run_type="llm", name="Generate Answer")
def generate(state: AgentState):
    """
    지식 리트리벌 결과 또는 액션 실행 결과를 바탕으로 최종 답변을 생성합니다.
    """
    print("---GENERATE---")
    question = state["question"]
    documents = state.get("documents", [])
    tool_outputs = state.get("tool_outputs", [])
    openai = get_openai_client()

    context = "\n\n".join(documents)
    
    # 도구 실행 결과 또는 시스템 메시지(예: 권한 확인 실패 사유)가 있는지 확인
    if state.get("generation") and state.get("action_status") == "failed":
        # check_eligibility 등에서 실패 사유가 넘어온 경우
        tool_context = f"액션 수행 불가 사유: {state.get('generation')}"
    elif tool_outputs:
        tool_context = json.dumps(tool_outputs, ensure_ascii=False, indent=2)
    else:
        tool_context = "실행된 액션 없음"
    
    system_prompt = GENERATION_SYSTEM_PROMPT_TEMPLATE.format(
        system_prompt=ECOMMERCE_SYSTEM_PROMPT,
        context=context,
        tool_context=tool_context
    )
    
    response = openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        temperature=0
    )
    
    final_answer = response.choices[0].message.content
    return {
        "generation": final_answer,
        "messages": [AIMessage(content=final_answer)]
    }

@traceable(run_type="chain", name="Handle No Info")
def no_info_node(state: AgentState):
    """
    검색 결과가 없을 때 실행되는 노드
    """
    print("---NO INFO FOUND---")
    msg = "죄송합니다. 문의하신 내용에 대한 답변을 지식베이스에서 찾을 수 없습니다. 구체적인 확인을 위해 고객센터(1588-XXXX)로 문의하시거나 상담원 연결을 도와드릴까요?"
    return {
        "generation": msg,
        "messages": [AIMessage(content=msg)]
    }

@traceable(run_type="parser", name="Mock NLU")
def mock_nlu(user_message: str) -> NLUResult:
    """
    [초고도화] 스코어링 기반 NLU 엔진
    문장 내 키워드 밀도를 계산하여 최적의 카테고리를 추론합니다.
    """
    # 전처리: 띄어쓰기 제거 및 소문자화
    clean_msg = user_message.replace(" ", "").lower()
    
    # 카테고리별 초정밀 키워드 사전 (데이터셋의 모든 세부 카테고리 반영)
    category_map = CATEGORY_KEYWORDS_MAP
    
    # 카테고리별 스코어 계산
    scores = {cat: 0 for cat in category_map}
    for cat, keywords in category_map.items():
        for k in keywords:
            if k in clean_msg:
                scores[cat] += 1
    
    # 점수가 높은 순으로 정렬
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_cat, max_score = sorted_scores[0]
    
    if max_score > 0:
        return NLUResult(intent=IntentType.INFO_SEARCH, slots={"category": best_cat})
    
    return NLUResult(intent=None, slots={})

@traceable(run_type="chain", name="LLM NLU Fallback")
def call_llm_for_nlu(user_message: str) -> dict:
    """
    키워드 매칭 실패 시 LLM을 사용하여 문맥 기반으로 의도(조회/실행)를 파악합니다.
    """
    openai = get_openai_client()
    
    system_prompt = NLU_SYSTEM_PROMPT
    
    response = openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        response_format={"type": "json_object"},
        temperature=0
    )
    
    res = json.loads(response.choices[0].message.content)
    res["is_relevant"] = res["category"] is not None
    return res

@traceable(run_type="chain", name="Check Action Eligibility")
def check_eligibility_node(state: AgentState):
    """
    액션 수행 전 주문 상태 등을 확인하여 수행 가능 여부를 판단합니다.
    """
    print("---CHECK ELIGIBILITY---")
    order_id = state.get("order_id")
    action = state.get("action_name")
    
    if not order_id:
        # 주문 번호가 없으면 주문 목록 조회(UI)로 유도
        print("---MISSING ORDER ID: REDIRECT TO ORDER LIST---")
        return {
            "action_name": ActionType.ORDER_LIST.value, 
            "action_status": "approved", # 바로 실행하러 감
            "is_relevant": True
        }
    
    user_id = state.get("user_id")
    # [Security Check]
    # We call get_order_details with user_id to verify ownership
    order = get_order_details.invoke({"order_id": order_id, "user_id": user_id})
    
    if "error" in order:
        return {
            "action_status": "failed", 
            "generation": order["error"],
            "messages": [AIMessage(content=order["error"])]
        }
        
    # 'refund' 의도인 경우 취소(배송전) 또는 반품(배송후) 가능 여부 통합 확인
    if action == ActionType.REFUND.value:
        # 1. 배송 전 -> 취소 가능 여부 확인 (check_cancellation)
        if order["status"] in ["pending", "paid"]:
            check_result = check_cancellation.invoke({"order_id": order_id, "user_id": user_id})
        # 2. 배송 후 -> 반품 가능 여부 확인 (check_return_eligibility)
        elif order["status"] in ["shipped", "delivered"]:
            # Mock: 단순 변심(사용자 귀책) 가정, 실제로는 사용자에게 사유를 물어봐야 함
            check_result = check_return_eligibility.invoke({
                "order_id": order_id, 
                "user_id": user_id, 
                "reason": "단순 변심", 
                "is_seller_fault": False
            })
        else:
            check_result = {"error": f"현재 {order['status']} 상태에서는 환불 처리가 불가능합니다."}

        # 검증 실패 시
        if "error" in check_result:
            return {
                "action_status": "failed", 
                "generation": check_result["error"],
                "messages": [AIMessage(content=check_result["error"])]
            }
            
        print("---REFUND/CANCEL PENDING APPROVAL---")
        return {
            "action_status": "pending_approval", 
            "refund_status": "pending_approval",
            # 도구가 생성한 안내 메시지(수수료 포함)와 환불 예정 금액 전달
            "generation": check_result.get("message"), 
            "refund_amount": check_result.get("final_refund_amount") or check_result.get("refund_amount")
        }

    # 결제 수단 변경은 배송 시작 전까지만 가능
    if action == ActionType.PAYMENT_UPDATE.value and order["status"] in ["shipped", "delivered"]:
        msg = f"죄송합니다. 현재 {order['status']} 상태여서 결제 수단을 변경할 수 없습니다."
        return {
            "action_status": "failed", 
            "generation": msg,
            "messages": [AIMessage(content=msg)]
        }
        
    return {"action_status": "approved"}

@traceable(run_type="chain", name="Human Approval")
def human_approval_node(state: AgentState):
    """
    사용자에게 액션 실행 여부를 묻는 메시지를 생성합니다.
    (check_eligibility에서 생성된 상세 메시지를 우선 사용)
    """
    print("---HUMAN APPROVAL REQUEST---")
    
    # 이미 생성된 메시지가 있다면 사용 (수수료 안내 등 포함됨)
    if state.get("generation"):
        return {
            "generation": state.get("generation"),
            "action_status": "pending_approval",
            "messages": [AIMessage(content=state.get("generation"))]
        }
    
    # Fallback (단순 메시지)
    order_id = state.get("order_id")
    amount = state.get("refund_amount", 0)
    msg = f"주문 번호 {order_id}의 환불(또는 취소) 예정 금액은 {amount:,}원입니다. 정말로 진행하시겠습니까? ('네' 또는 '아니오'로 답해주세요)"
    
    return {
        "generation": msg,
        "action_status": "pending_approval",
        "messages": [AIMessage(content=msg)]
    }

def execute_action_node(state: AgentState):
    """
    실제 API 도구를 호출하여 액션을 수행합니다.
    """
    print("---EXECUTE ACTION---")
    action = state.get("action_name")
    order_id = state.get("order_id")
    user_id = state.get("user_id")
    # user_info에 저장된 파라미터 활용
    params = state.get("user_info", {})
    
    result = {}
    
    # 1. 환불/취소 (통합 'refund' 인텐트 처리)
    if action == ActionType.REFUND.value:
        # 상태 재확인하여 취소 vs 반품 결정
        order_info = get_order_details.invoke({"order_id": order_id, "user_id": user_id})
        if order_info.get("can_cancel"):
             # 배송 전 -> 취소 실행
             result = cancel_order.invoke({"order_id": order_id, "user_id": user_id, "reason": "사용자 요청"})
        elif order_info.get("can_return"):
             # 배송 후 -> 반품 실행 (pickup_address 필요하나 여기서는 기본값 처리 혹은 추가 대화 필요)
             # Mock: 기본 주소 사용
             result = register_return_request.invoke({"order_id": order_id, "user_id": user_id, "pickup_address": "등록된 배송지"})
        else:
             result = {"error": "실행 시점에 취소/반품 가능 상태가 아닙니다."}
             
    # 2. 배송 조회 (통합)
    elif action == ActionType.TRACKING.value or action == ActionType.COURIER_CONTACT.value:
        result = get_shipping_details.invoke({"order_id": order_id, "user_id": user_id})
        
    elif action == ActionType.ORDER_DETAIL.value:
        result = get_order_details.invoke({"order_id": order_id, "user_id": user_id})
        
    elif action == ActionType.PAYMENT_UPDATE.value:
        payment_method = params.get("payment_method", "카드") # 기본값 카드
        result = update_payment_method.invoke({"order_id": order_id, "user_id": user_id, "payment_method": payment_method})
        
    elif action == ActionType.GIFT_CARD.value:
        code = params.get("gift_card_code", "UNKNOWN")
        result = register_gift_card.invoke({"code": code})
        
    elif action == ActionType.REVIEW_SEARCH.value:
        result = get_reviews.invoke({"limit": 5})
        
    elif action == ActionType.REVIEW_CREATE.value:
        product_id = params.get("product_id", "PROD-001")
        rating = params.get("review_rating", 5)
        content = params.get("review_content", "좋아요")
        result = create_review.invoke({"product_id": product_id, "rating": rating, "content": content})
        
    elif action == ActionType.ADDRESS_CHANGE.value:
        # 주소지 변경 Mock
        result = {"success": True, "message": f"주문 {order_id}의 주소지가 성공적으로 변경되었습니다."}
        
    elif action == ActionType.ORDER_LIST.value:
        # Retrieve user_id from state
        result = get_user_orders.invoke({"user_id": user_id})
        
    return {
        "action_status": "completed",
        "tool_outputs": [result]
    }


@traceable(run_type="chain", name="Query Rewriting")
def rewrite_query(original_query: str, history: List[Any]) -> str:
    """
    이전 대화 기록을 바탕으로 현재 질문을 재작성합니다.
    """

    if not history:
        return original_query
        
    # 최근 대화 2턴(사용자-AI) 정도만 참고해도 충분한 경우가 많음
    recent_history = history[-6:] 
    history_str = "\n".join([f"{msg.type}: {msg.content}" for msg in recent_history])
    
    openai = get_openai_client()
    # settings에 정의된 값이 있으면 우선 사용, 없으면 import한 기본값 사용
    system_prompt = getattr(settings, "QUERY_REWRITE_PROMPT", QUERY_REWRITE_PROMPT) 
    
    try:
        response = openai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"History:\n{history_str}\n\nCurrent: {original_query}"}
            ],
            temperature=0
        )
        rewritten = response.choices[0].message.content.strip()
        print(f"--- QUERY REWRITTEN: '{original_query}' -> '{rewritten}' ---")
        return rewritten
    except Exception as e:
        print(f"Error in query rewriting: {e}")
        return original_query

@traceable(run_type="chain", name="Update State")
def update_state_node(state: AgentState) -> dict:
    """
    [하이브리드 NLU] 질문을 분석하여 '조회'인지 '실행'인지 결정합니다.
    (Query Rewriting 추가됨)
    """
    print("---UPDATE STATE (Intelligent Action NLU)---")
    messages = state.get("messages", [])
    
    # 0. 메시지 추출
    if not messages:
        return {}
        
    last_message = messages[-1]
    original_content = last_message.content if hasattr(last_message, "content") else str(last_message)
    
    # 1. 쿼리 재작성 (대화 이력이 있는 경우)
    # 현재 메시지를 제외한 이전 이력
    history = messages[:-1]
    refined_question = original_content
    
    if history:
         refined_question = rewrite_query(original_content, history)
    
    # 2. 문서 검색용 카테고리 추출 (재작성된 쿼리 사용)
    nlu_keyword = mock_nlu(refined_question)
    
    # 3. 액션 파악을 위한 LLM 분석 (intent_type, action_name, order_id 추출)
    # 질문에서 주문번호(ORD-XXX) 추출 시도 (원본/재작성 둘 다 체크)
    order_id_match = re.search(r"ORD-\d+", original_content) or re.search(r"ORD-\d+", refined_question)
    order_id = order_id_match.group() if order_id_match else state.get("order_id")
    
    llm_analysis = call_llm_for_nlu(refined_question)
    
    # [승인 루프 처리] 현재 대기 중인 액션이 있고 사용자가 응답한 경우
    current_status = state.get("action_status")
    
    # 3-1. 새로운 의도(Intent)가 감지되었는지 확인 (Context Switching)
    new_intent_detected = False
    if current_status == "pending_approval":
        if llm_analysis.get("action_name") and llm_analysis.get("intent_type") == IntentType.EXECUTION.value:
             print("---CONTEXT SWITCH DETECTED: NEW INTENT OVERRIDES APPROVAL---")
             new_intent_detected = True

    if current_status == "pending_approval" and not new_intent_detected:
        positive_words = ["네", "어", "예", "응", "그래", "확인", "진행", "yes", "ok"]
        content_lower = original_content.lower() # 승인/거절은 원본 의도 중요
        if any(word in content_lower for word in positive_words):
            print("---USER APPROVED ACTION---")
            return {
                "action_status": "approved",
                "is_relevant": True
            }
        elif any(word in content_lower for word in ["싫어", "아니", "취소", "no", "stop"]):
            print("---USER CANCELLED ACTION---")
            return {
                "action_status": "failed",
                "generation": "환불 요청이 취소되었습니다. 대화를 종료하거나 다른 문의를 도와드릴까요?",
                "is_relevant": True
            }

    # 파라미터 추출 및 상태 업데이트
    parameters = llm_analysis.get("parameters", {}) or {}
    print(f"Detected Parameters: {parameters}")
    
    extracted_order_id = parameters.get("order_id") or order_id
    
    updates = {
        "question": refined_question, # NLU와 검색에 사용될 정제된 질문
        "category": llm_analysis["category"] or (nlu_keyword.slots.get("category") if nlu_keyword.intent else None),
        "intent_type": llm_analysis["intent_type"],
        "action_name": llm_analysis["action_name"] or state.get("action_name"),
        "order_id": extracted_order_id,
        "is_relevant": llm_analysis["is_relevant"],
        "action_status": "idle" if new_intent_detected else state.get("action_status", "idle"), 
        "tool_outputs": [],
        "action_status": "idle" if new_intent_detected else state.get("action_status", "idle"), 
        "tool_outputs": [],
        "user_info": {**state.get("user_info", {}), **parameters},
        
        # [Security] Auth is now handled by API (chat.py)
        # "user_id": 7, 
        # "is_authenticated": True 
    }
    
    print(f"Intent: {updates['intent_type']}, Action: {updates['action_name']}, Order: {updates['order_id']}")
    return updates
