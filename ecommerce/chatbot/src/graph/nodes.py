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
from ecommerce.chatbot.src.services.mock_services import get_order_details, request_refund, get_tracking_info

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
    tool_context = str(tool_outputs)
    
    system_prompt = f"""당신은 이커머스 고객센터의 유능한 에이전트입니다.
    사용자의 질문에 대해 [지식 베이스] 또는 [액션 실행 결과]를 바탕으로 정확하고 친절한 답변을 제공하세요.
    
    [지식 베이스]: {context}
    [액션 실행 결과]: {tool_context}
    
    - 실행 결과가 있다면 그 내용을 최우선으로 안내하세요.
    - 지식 베이스에 관련 내용이 있다면 이를 보충 설명으로 활용하세요.
    - 한국어로 정중하게 작성하세요."""
    
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
    category_map = {
        "배송": [
            "배송", "택배", "송장", "언제", "도착", "출고", "추적", "기한", "수령", "배달", "영업일", "지연", 
            "주문제작", "포장", "방문", "퀵", "해외", "도서산간", "제주", "추가비용", "착불", "선불", "묶음", 
            "새벽", "당일", "매장", "합배송", "분리배송", "군부대", "사서함", "안심번호", "기사님", "현관", 
            "경비실", "배송완료", "미수령", "택배사", "운송장", "부재중", "출고지", "수령인", "배송지변경", "배송료", "배송비"
        ],
        "취소/반품/교환": [
            "취소", "반품", "교환", "환불", "철회", "거절", "거부", "회수", "반송", "하자", "누락", "오배송", 
            "반송비", "철회권", "멸실", "훼손", "사용감", "감가", "위약금", "부분취소", "자동취소", "단순변심", 
            "접수", "맞교환", "라벨제거", "택제거", "오연", "박스훼손", "심의", "반환", "청약철회", "교환권",
            "환급", "수거", "회수접수", "반송비용", "교환신청", "반품신청", "전액환불", "부분환불", "카드취소",
            "작아요", "커요", "작네", "크네", "안맞아요"
        ],
        "주문/결제": [
            "결제", "입금", "카드", "주문", "구매", "머니", "상품권", "포인트", "적립금", "가상계좌", "무통장", 
            "실적", "대금", "영수증", "지불", "유효기간", "소멸", "충전", "전환", "미성년자", "법정대리인", 
            "간편결제", "페이", "할부", "복합결제", "세금계산서", "증빙", "지출", "수단", "입금확인", "복구", 
            "임직원", "예치금", "선입금", "송금", "현금", "에스크로", "안전결제", "무통", "무이자", "입금자명", 
            "은행", "결제오류", "자동입금", "미납", "미결제", "영수증발행", "카드사", "체크카드", "구매/결제"
        ],
        "회원 정보": [
            "회원", "가입", "로그인", "비밀번호", "아이디", "탈퇴", "개인정보", "인증", "본인확인", "혜택", 
            "등급", "마이메뉴", "쿠폰", "개명", "휴대폰", "연동", "소셜", "계정", "통합", "초기화", "수정", 
            "아이디찾기", "비회원", "휴면", "정지", "제한", "말소", "소명", "마케팅", "수신동의", "알림", 
            "푸시", "아이핀", "본인명의", "변경", "기기등록", "기기차단", "명의변경", "닉네임", "정보변경",
            "계정찾기", "비밀번호분실", "정보수정", "프로필", "약관동의", "회원혜택", "생일선물", "마일리지", "sns"
        ],
        "상품/AS 문의": [
            "상품", "사이즈", "정품", "가품", "as", "수선", "불량", "재고", "품절", "재입고", "사은품", 
            "검수", "보증서", "디자인", "추천", "브랜드", "리뷰", "후기", "보상", "모조품", "병행수입", 
            "재판매", "리셀", "가짜", "위조", "도용", "라벨", "래플", "추첨", "응모", "이벤트", "체험단", 
            "당첨", "가이드", "실측", "소재", "원단", "마감", "박음질", "핏", "착용감", "색상", "오프라인",
            "디테일", "모델컷", "코디", "사이즈표", "실측데이터", "정품확인", "as접수", "수선비", "재입고알림", 
            "재고현황", "세탁", "케어", "혼용률", "옷", "의류", "신발", "가방", "액세서리", "크기", "착용"
        ],
        "약관": [
            "약관", "법", "책임", "의무", "저작권", "분쟁", "이용안내", "규정", "조항", "목적", "정의", "개정", 
            "준용", "손해배상", "합의", "동의", "처리방침", "면책", "상관례", "지침", "소비자보호법", "관할", 
            "소송", "점검", "장애", "오류", "해킹", "보안", "공정거래위원회", "고의", "과실", "입증", 
            "표준약관", "권리", "의무", "지식재산권", "전자상거래법", "이용규칙", "준수", "분쟁조정", "민형사",
            "서비스", "이용 안내", "개인정보", "분쟁해결", "의무/책임", "일반", "연결몰"
        ]
    }
    
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
    
    system_prompt = f"""당신은 고객센터 의도 분석 전문가입니다. 사용자의 질문을 분석하여 JSON 형식으로 응답하세요.

    [분류 가이드]
    1. category: 배송, 취소/반품/교환, 주문/결제, 회원 정보, 상품/AS 문의, 약관 중 선택
    2. intent_type: 질문이 정보 조회면 'info_search', 실제 처리 요청(환불해줘, 배송 어디야 등)이면 'execution'
    3. action_name: 실행 요청인 경우 'refund'(환불/취소), 'tracking'(배송조회), 'address_change'(주소변경) 중 선택 (아니면 null)

    [카테고리 상세 가이드]
    1. 배송: 배송 일정, 택배사, 송장, 도착 등 (키워드: 배송, 택배, 송장, 언제, 도착, 출고 등)
    2. 취소/반품/교환: 환불, 취소, 교환, 반품, 작아요, 커요 등 (키워드: 취소, 반품, 교환, 환불, 철회 등)
    3. 주문/결제: 결제수단, 입금확인, 영수증 등 (키워드: 결제, 입금, 카드, 주문, 구매 등)
    4. 회원 정보: 비밀번호, 아이디찾기, 탈퇴 등 (키워드: 회원, 가입, 로그인, 비밀번호, 아이디 등)
    5. 상품/AS 문의: 제품 상세, 사이즈, AS, 수선 등 (키워드: 상품, 사이즈, 정품, 가품, as, 수선 등)
    6. 약관: 법적 책임, 이용규정 등 (키워드: 약관, 법, 책임, 의무, 저작권 등)

    응답 예시: {{"category": "배송", "intent_type": "execution", "action_name": "tracking"}}"""
    
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
    
    order = get_order_details(order_id)
    if not order:
        return {"action_status": "failed", "generation": "해당 주문 번호를 찾을 수 없습니다."}
        
    if action == "refund" and not order["can_refund"]:
        return {"action_status": "failed", "generation": f"이 주문은 현재 {order['status']} 상태로 환불이 불가능합니다."}
        
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

@traceable(run_type="chain", name="Execute Action Tool")
def execute_action_node(state: AgentState):
    """
    실제 API 도구를 호출하여 액션을 수행합니다.
    """
    print("---EXECUTE ACTION---")
    action = state.get("action_name")
    order_id = state.get("order_id")
    
    result = {}
    if action == "refund":
        result = request_refund(order_id, "사용자 요청")
    elif action == "tracking":
        result = get_tracking_info(order_id)
        
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

    updates = {
        "question": content,
        "category": llm_analysis["category"] or (nlu_keyword.slots.get("category") if nlu_keyword.intent else None),
        "intent_type": llm_analysis["intent_type"],
        "action_name": llm_analysis["action_name"] or state.get("action_name"),
        "order_id": order_id,
        "is_relevant": llm_analysis["is_relevant"],
        "action_status": "idle",
        "tool_outputs": []
    }
    
    print(f"Intent: {updates['intent_type']}, Action: {updates['action_name']}, Order: {updates['order_id']}")
    return updates
