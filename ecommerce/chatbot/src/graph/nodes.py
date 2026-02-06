import re
import json
from typing import List, Optional, Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from qdrant_client import models
from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.schemas.nlu import NLUResult
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings
# 신규 프롬프트 및 도구 임포트
from ecommerce.chatbot.src.prompts.system_prompts import (
    ECOMMERCE_SYSTEM_PROMPT, 
    NLU_SYSTEM_PROMPT, 
    GENERATION_SYSTEM_PROMPT_TEMPLATE,
    CATEGORY_KEYWORDS_MAP
)
from ecommerce.chatbot.src.tools.order_tools import (
    get_delivery_status, 
    get_courier_contact, 
    update_payment_info, 
    request_refund, 
    get_order_details
)
from ecommerce.chatbot.src.tools.service_tools import register_gift_card, get_reviews, create_review

@traceable(run_type="retriever", name="Retrieve Documents")
def retrieve(state: AgentState):
    """
    Retrieve documents from Qdrant.
    [통합 검색] 카테고리 필터 검색과 전체 검색 결과를 병합하여 최적의 문서를 찾습니다.
    """
    print("---RETRIEVE---")
    question = state["question"]
    category = state.get("category")
    client = get_qdrant_client()
    openai = get_openai_client()

    # 1. 질문 임베딩 생성
    emb_response = openai.embeddings.create(
        input=question,
        model=settings.EMBEDDING_MODEL
    )
    query_vector = emb_response.data[0].embedding

    # 2. 검색 전략 실행
    collections = [settings.COLLECTION_FAQ, settings.COLLECTION_TERMS]
    combined_results = {} # point ID를 키로 사용하여 중복 제거

    for col in collections:
        # A. 카테고리 필터 검색 (카테고리가 인식된 경우만)
        if category:
            if col == settings.COLLECTION_FAQ:
                field_name = "main_category"
                mapped_category = "취소/교환/반품" if category == "취소/반품/교환" else category
            else: # COLLECTION_TERMS
                field_name = "category"
                if category == "회원 정보": mapped_category = "회원"
                elif category == "주문/결제": mapped_category = "구매/결제"
                else: mapped_category = category

            try:
                filtered_res = client.query_points(
                    collection_name=col,
                    query=query_vector,
                    query_filter=models.Filter(
                        must=[models.FieldCondition(key=field_name, match=models.MatchValue(value=mapped_category))]
                    ),
                    limit=3
                ).points
                for hit in filtered_res:
                    combined_results[hit.id] = hit
            except Exception as e:
                print(f"Error filtered searching {col}: {e}")

        # B. 전체 대상 검색 (카테고리 제한 없음)
        try:
            global_res = client.query_points(
                collection_name=col,
                query=query_vector,
                limit=3
            ).points
            for hit in global_res:
                if hit.id not in combined_results:
                    combined_results[hit.id] = hit
        except Exception as e:
            print(f"Error global searching {col}: {e}")

    # 3. 점수 순 정렬 및 상위 5개 추출
    sorted_hits = sorted(combined_results.values(), key=lambda x: x.score, reverse=True)[:5]
    
    # 4. 페이로드 가공 및 유사도 검증
    all_documents = []
    for hit in sorted_hits:
        if hit.score > 0.2:
            # Note: Determine doc_type based on the hit metadata or loop context
            # simplified for resolution here. In complex logic, we might track col.
            payload = hit.payload
            doc_type = "정보" # Default
            if 'main_category' in payload: doc_type = "FAQ"
            elif 'category' in payload: doc_type = "약관"

            content_text = (
                payload.get('question', '') + " " + payload.get('answer', '') if payload.get('question') else
                payload.get('text', '') or 
                payload.get('content', '') or 
                payload.get('title', '')
            ).strip()
            
            if content_text:
                all_documents.append(f"[{doc_type}] {content_text}")

    print(f"최종 병합 및 필터링된 문서 수: {len(all_documents)}")
    
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
    
    # 도구 실행 결과를 명확한 JSON 문자열로 변환
    if tool_outputs:
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
    
    return {"generation": response.choices[0].message.content}

@traceable(run_type="chain", name="Handle No Info")
def no_info_node(state: AgentState):
    """
    검색 결과가 없을 때 실행되는 노드
    """
    print("---NO INFO FOUND---")
    return {
        "generation": "죄송합니다. 문의하신 내용에 대한 답변을 지식베이스에서 찾을 수 없습니다. 구체적인 확인을 위해 고객센터(1588-XXXX)로 문의하시거나 상담원 연결을 도와드릴까요?"
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
        return NLUResult(intent="search_knowledge", slots={"category": best_cat})
    
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
        return {"action_status": "failed", "generation": "주문 번호가 없어 확인이 불가능합니다. 주문 번호를 알려주시겠어요?"}
    
    order = get_order_details.invoke({"order_id": order_id})
    if not order:
        return {"action_status": "failed", "generation": "해당 주문 번호를 찾을 수 없습니다."}
        
    if action == "refund" and not order["can_refund"]:
        return {"action_status": "failed", "generation": f"이 주문은 현재 {order['status']} 상태로 환불이 불가능합니다."}

    if action == "payment_update" and order["status"] in ["배송중", "배송완료"]:
        return {"action_status": "failed", "generation": f"죄송합니다. 현재 {order['status']} 상태여서 결제 수단을 변경할 수 없습니다."}
        
    # 환불은 승인 루프(Human-in-the-loop) 진입, 기타 액션은 바로 승인
    if action == "refund":
        print("---REFUND PENDING APPROVAL---")
        return {
            "action_status": "pending_approval", 
            "refund_status": "pending_approval",
            "refund_amount": order.get("amount")
        }
        
    return {"action_status": "approved"}

@traceable(run_type="chain", name="Human Approval")
def human_approval_node(state: AgentState):
    """
    사용자에게 액션 실행 여부를 묻는 메시지를 생성합니다.
    """
    print("---HUMAN APPROVAL REQUEST---")
    order_id = state.get("order_id")
    amount = state.get("refund_amount", 0)
    
    msg = f"주문 번호 {order_id}의 환불 예정 금액은 {amount:,}원입니다. 정말로 환불을 진행하시겠습니까? ('네' 또는 '아니오'로 답해주세요)"
    
    return {
        "generation": msg,
        "action_status": "pending_approval"
    }

def execute_action_node(state: AgentState):
    """
    실제 API 도구를 호출하여 액션을 수행합니다.
    """
    print("---EXECUTE ACTION---")
    action = state.get("action_name")
    order_id = state.get("order_id")
    # user_info에 저장된 파라미터 활용
    params = state.get("user_info", {})
    
    result = {}
    if action == "refund":
        result = request_refund.invoke({"order_id": order_id, "reason": "사용자 요청"})
    elif action == "tracking":
        result = get_delivery_status.invoke({"order_id": order_id})
    elif action == "courier_contact":
        result = get_courier_contact.invoke({"order_id": order_id})
    elif action == "payment_update":
        payment_method = params.get("payment_method", "카드") # 기본값 카드
        result = update_payment_info.invoke({"order_id": order_id, "payment_method": payment_method})
    elif action == "gift_card":
        code = params.get("gift_card_code", "UNKNOWN")
        result = register_gift_card.invoke({"code": code})
    elif action == "review_search":
        result = get_reviews.invoke({"limit": 5})
    elif action == "review_create":
        product_id = params.get("product_id", "PROD-001")
        rating = params.get("review_rating", 5)
        content = params.get("review_content", "좋아요")
        result = create_review.invoke({"product_id": product_id, "rating": rating, "content": content})
    elif action == "address_change":
        # 주소지 변경 Mock
        result = {"success": True, "message": f"주문 {order_id}의 주소지가 성공적으로 변경되었습니다."}
        
    return {
        "action_status": "completed",
        "tool_outputs": [result]
    }


@traceable(run_type="chain", name="Update State")
def update_state_node(state: AgentState) -> dict:
    """
    [하이브리드 NLU] 질문을 분석하여 '조회'인지 '실행'인지 결정합니다.
    """
    print("---UPDATE STATE (Intelligent Action NLU)---")
    messages = state.get("messages", [])
    content = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])
    
    # 1. 문서 검색용 카테고리 추출 (기존 mock_nlu 활용)
    nlu_keyword = mock_nlu(content)
    
    # 2. 액션 파악을 위한 LLM 분석 (intent_type, action_name, order_id 추출)
    # 질문에서 주문번호(ORD-XXX) 추출 시도
    order_id_match = re.search(r"ORD-\d+", content)
    order_id = order_id_match.group() if order_id_match else state.get("order_id")
    
    llm_analysis = call_llm_for_nlu(content)
    
    # [승인 루프 처리] 현재 대기 중인 액션이 있고 사용자가 긍정적인 답변을 한 경우
    current_status = state.get("action_status")
    if current_status == "pending_approval":
        positive_words = ["네", "어", "예", "응", "그래", "확인", "진행", "yes", "ok"]
        content_lower = content.lower()
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
    
    # 3. 주문 번호 우선순위: 파라미터 > 정규식 > 기존 상태
    extracted_order_id = parameters.get("order_id") or order_id
    
    updates = {
        "question": content,
        "category": llm_analysis["category"] or (nlu_keyword.slots.get("category") if nlu_keyword.intent else None),
        "intent_type": llm_analysis["intent_type"],
        "action_name": llm_analysis["action_name"] or state.get("action_name"),
        "order_id": extracted_order_id,
        "is_relevant": llm_analysis["is_relevant"],
        "action_status": "idle",
        "tool_outputs": [],
        # 추후 도구 실행에 필요한 파라미터들을 user_info에 병합하여 저장
        "user_info": {**state.get("user_info", {}), **parameters}
    }
    
    print(f"Intent: {updates['intent_type']}, Action: {updates['action_name']}, Order: {updates['order_id']}")
    return updates
