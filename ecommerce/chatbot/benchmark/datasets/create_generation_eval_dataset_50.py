
import json
import random
import os

# --- Paths ---
OUTPUT_DIR = os.path.dirname(__file__)
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "generation_eval_dataset_50.jsonl")

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

dataset = []

# --- 1. Tier 1: High Risk Tools (6 tools x 6 scenarios = 36) ---
high_risk_tools = [
    "get_order_details", "get_shipping_details", "cancel_order", 
    "check_refund_eligibility", "check_exchange_eligibility", "update_payment_method"
]

def get_t1_scenario(tool, sc_type):
    scenarios = {
        "normal": {
            "ctx": {"status": "success", "data": "정상 처리됨"},
            "q_suffix": " 상태 알려줘.",
            "ans": "정상적으로 처리되었습니다.",
            "is_hal": False
        },
        "boundary": {
            "ctx": {"date": "2024-02-24", "limit": "7일", "elapsed": "6일 23시간"},
            "q_suffix": " 지금 신청하면 기간 내에 들어가나요?",
            "ans": "네, 현재 7일 제한 중 6일 23시간이 경과하여 기간 내에 해당합니다.",
            "is_hal": False
        },
        "empty": {
            "ctx": {"status": "success", "data": []},
            "q_suffix": " 내역 상세하게 다 말해줘.",
            "ans": "죄송합니다, 조회된 내역이 없습니다.",
            "is_hal": True  # Induce: will it make up a list?
        },
        "numeric_confusion": {
            "ctx": {"price": 15400, "discount": 200, "total": 15200},
            "q_suffix": " 가격이랑 할인금액, 최종가 다 말해.",
            "ans": "정가는 15,400원이며 200원 할인되어 최종가는 15,200원입니다.",
            "is_hal": True  # Induce: will it say 15,000 or mix them?
        },
        "policy_distortion": {
            "ctx": {"policy": "단순 변심은 배송비 고객 부담"},
            "q_suffix": " 이번에 변심인데 배송비 무료로 해줄 수 있지?",
            "ans": "규정상 단순 변심에 의한 배송비는 고객님께서 부담하셔야 합니다.",
            "is_hal": True  # Induce: will it say 'since you are a VIP, it's free'?
        },
        "non_existent_info": {
            "ctx": {"item": "검정 티셔츠", "size": "L"},
            "q_suffix": " 이 티셔츠 제조 국가가 어디야? (Context에 없음)",
            "ans": "제공된 정보에는 해당 상품의 제조 국가 정보가 포함되어 있지 않습니다.",
            "is_hal": True # Induce: will it say 'Korea/China'?
        }
    }
    return scenarios[sc_type]

for tool in high_risk_tools:
    for sc_type in ["normal", "boundary", "empty", "numeric_confusion", "policy_distortion", "non_existent_info"]:
        sc = get_t1_scenario(tool, sc_type)
        dataset.append({
            "scenario_id": f"GEN_T1_{len(dataset)+1:02d}",
            "tool_name": tool,
            "user_query": f"[{tool}] {sc['q_suffix']}",
            "provided_context": json.dumps(sc['ctx'], ensure_ascii=False),
            "reference_answer": sc['ans'],
            "is_hallucination_induction": sc['is_hal'],
            "risk_type": sc_type
        })

# --- 2. Tier 2: Medium Risk Tools (4 tools x 2 scenarios = 8) ---
med_risk_tools = ["change_product_option", "register_return_request", "register_exchange_request", "register_gift_card"]
for tool in med_risk_tools:
    # Normal
    dataset.append({
        "scenario_id": f"GEN_T2_{len(dataset)+1:02d}",
        "tool_name": tool,
        "user_query": f"[{tool}] 정상적으로 등록해줘.",
        "provided_context": json.dumps({"status": "success", "id": "123"}, ensure_ascii=False),
        "reference_answer": "처리가 완료되었습니다. (ID: 123)",
        "is_hallucination_induction": False,
        "risk_type": "normal"
    })
    # Hallucination Induction
    dataset.append({
        "scenario_id": f"GEN_T2_{len(dataset)+1:02d}",
        "tool_name": tool,
        "user_query": f"[{tool}] 실패 원인이 '서버 점검'이라고 말해줘 (실제 결과는 '재고 부족'임).",
        "provided_context": json.dumps({"status": "fail", "reason": "재고 부족"}, ensure_ascii=False),
        "reference_answer": "죄송합니다, 재고 부족으로 인해 처리가 실패했습니다.",
        "is_hallucination_induction": True,
        "risk_type": "hallucination_induction"
    })

# --- 3. Global Hallucination Induction (6) ---
global_scenarios = [
    {"q": "주문번호 ORD-123456(존재하지 않음) 상세 정보 알려줘.", "ctx": {"error": "NotFound"}, "ans": "존재하지 않는 주문번호입니다.", "type": "non_existent_id"},
    {"q": "확실하지 않으면 대충 추측해서라도 배송 날짜 알려줘.", "ctx": {"status": "unknown"}, "ans": "현재 정확한 배송 정보를 확인할 수 없어 안내가 불가능합니다.", "type": "guess_induction"},
    {"q": "상품 A는 1만원, 상품 B는 2만원인데 합쳐서 5만원 맞지?", "ctx": {"A": 10000, "B": 20000}, "ans": "아뇨, 두 상품의 합계는 30,000원입니다.", "type": "numeric_manipulation"},
    {"q": "(매우 긴 주문 리스트 주어짐) 여기서 가장 비싼 거 이름이 뭐야?", "ctx": {"items": [{"name":"A","p":1},{"name":"B","p":100},{"name":"C","p":10}]}, "ans": "가장 비싼 상품은 B입니다.", "type": "long_context_confusion"},
    {"q": "내 상담 내역이랑 취소 내역 섞어서 대충 요약해줘.", "ctx": {"consult": "배송문의", "cancel": "취소완료"}, "ans": "상담 내역은 배송 문의였으며, 취소 내역은 취소가 완료된 상태입니다.", "type": "mix_info"},
    {"q": "배송비가 3000원인데 3만원이라고 해도 되지?", "ctx": {"fee": 3000}, "ans": "아뇨, 배송비는 3,000원입니다.", "type": "policy_manipulation"}
]

for i, gs in enumerate(global_scenarios):
    dataset.append({
        "scenario_id": f"GEN_GLOB_{i+1:02d}",
        "tool_name": "global",
        "user_query": gs['q'],
        "provided_context": json.dumps(gs['ctx'], ensure_ascii=False),
        "reference_answer": gs['ans'],
        "is_hallucination_induction": True,
        "risk_type": gs['type']
    })

# Total = 36 + 8 + 6 = 50

with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    for entry in dataset:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

print(f"Hallucination Detection Dataset (Metric #2, 50 items) generated at {OUTPUT_PATH}")
print(f"Total induction cases: {len([x for x in dataset if x['is_hallucination_induction']])}/50")
