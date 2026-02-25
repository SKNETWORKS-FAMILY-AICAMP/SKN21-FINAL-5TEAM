
import json
import pandas as pd
import random
import os
import re

# --- Paths ---
PATH_AIHUB_FASHION = r"C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\AI_Hub\패션_validation.csv"
PATH_AIHUB_CLOTHING = r"C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\AI_Hub\의류_validation.csv"
PATH_AIHUB_GOODS = r"C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\AI_Hub\생활잡화_validation.csv"
PATH_ECOMMERCE_STANDARD = r"C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\ecommerce_standard\ecommerce_standard_preprocessed.json"
PATH_MUSINSA_FAQ = r"C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\musinsa_faq\musinsa_faq_20260203_162139_final.json"
OUTPUT_DIR = r"C:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\chatbot_eval\datasets"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "argument_accuracy_dataset_200.jsonl")

# Ensure output directory exists
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f: return json.load(f)

def load_csv(path):
    try: return pd.read_csv(path, encoding='utf-8')
    except: return pd.read_csv(path, encoding='cp949')

# --- Data Preparation ---
faq_data = load_json(PATH_MUSINSA_FAQ)
std_data = load_json(PATH_ECOMMERCE_STANDARD)
csv_paths = [PATH_AIHUB_FASHION, PATH_AIHUB_CLOTHING, PATH_AIHUB_GOODS]
aihub_queries = []
for p in csv_paths:
    if os.path.exists(p):
        df = load_csv(p)
        aihub_queries.extend(df[df['발화자'] == 'c']['발화문'].tolist())

# --- Schema Mapping --- 
# Groups: A(80), B(40), C(50), D(30)
# Total 200

def get_random_order_id():
    return f"ORD-{random.randint(2025, 2026)}{random.randint(0, 12):02d}{random.randint(1, 28):02d}-{random.randint(1000, 9999)}"

def get_random_product_id():
    return f"PRD-{random.randint(100000, 999999)}"

reasons = ["단순 변심", "사이즈 불만", "오배송", "상품 불량", "색상 상이"]
payment_methods = ["신용카드", "계좌이체", "카카오페이", "네이버페이", "무통장입금"]
options = ["블랙 / L", "화이트 / M", "Blue / XL", "Red / S"]

dataset = []

# Distribution requirements
groups = {
    "A": {"count": 80, "tools": ["cancel_order", "check_refund_eligibility", "check_exchange_eligibility", "register_return_request", "register_exchange_request"]},
    "B": {"count": 40, "tools": ["get_order_details", "get_shipping_details", "search_knowledge_base"]},
    "C": {"count": 50, "tools": ["update_payment_method", "change_product_option", "open_address_search", "save_shipping_address_from_ui"]},
    "D": {"count": 30, "tools": ["get_reviews", "create_review", "register_gift_card"]}
}

diff_counts = {"easy": 90, "medium": 80, "hard": 30}
source_counts = {"aihub": 70, "chatbot": 130}

# Mapping tools to their specific argument logic
def generate_args(tool, difficulty):
    order_id = get_order_id_format(difficulty)
    if tool in ["cancel_order", "register_return_request", "register_exchange_request"]:
        args = {"order_id": order_id, "reason": random.choice(reasons)}
        if tool == "register_exchange_request":
            args["new_option"] = random.choice(options)
        return args
    elif tool in ["get_order_details", "get_shipping_details", "check_refund_eligibility", "check_exchange_eligibility"]:
        return {"order_id": order_id}
    elif tool == "update_payment_method":
        return {"order_id": order_id, "payment_method": random.choice(payment_methods)}
    elif tool == "change_product_option":
        return {"order_id": order_id, "new_option": random.choice(options)}
    elif tool == "save_shipping_address_from_ui":
        return {"order_id": order_id, "address": "서울시 강남구 테헤란로 123"}
    elif tool == "search_knowledge_base":
        return {"query": "배송비 정책 알려줘", "category": "배송"}
    elif tool == "open_address_search":
        return {"query": "강남역"}
    elif tool == "get_reviews":
        return {"product_id": get_random_product_id()}
    elif tool == "create_review":
        return {"order_id": order_id, "product_id": get_random_product_id(), "rating": random.randint(1, 5), "review_text": "좋아요"}
    elif tool == "register_gift_card":
        return {"gift_card_code": f"GFT-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"}
    return {}

def get_order_id_format(difficulty):
    oid = get_random_order_id()
    if difficulty == "hard":
        fmt = random.choice(["short", "noise", "none"])
        if fmt == "short": return oid.split('-')[-1]
        if fmt == "noise": return oid + "입니다"
    return oid

# Generator loop
all_entries = []

# Flatten groups to a list of tool slots
slots = []
for g_key, g_val in groups.items():
    tools_for_group = g_val['tools']
    for _ in range(g_val['count']):
        slots.append(random.choice(tools_for_group))

random.shuffle(slots)

# Assign difficulty and source
difficulties = ["easy"] * 90 + ["medium"] * 80 + ["hard"] * 30
random.shuffle(difficulties)
sources = ["aihub"] * 70 + ["chatbot"] * 130
random.shuffle(sources)

for i in range(200):
    tool = slots[i]
    diff = difficulties[i]
    src = sources[i]
    
    # Base query
    if src == "aihub" and aihub_queries:
        base_q = random.choice(aihub_queries)
    else:
        # Chatbot/Synthetic
        if tool == "cancel_order": base_q = "주문 취소하고 싶어요"
        elif tool == "get_order_details": base_q = "내 주문 내역 보여줘"
        else: base_q = f"{tool} 관련 문의입니다."

    args = generate_args(tool, diff)
    
    # Refine query based on args and difficulty
    q = base_q
    if "order_id" in args:
        q += f" 주문번호는 {args['order_id']}예요."
    if "reason" in args:
        q += f" 사유는 {args['reason']}입니다."
    if "new_option" in args:
        q += f" {args['new_option']} 사이즈로 변경할게요."
    
    if diff == "hard":
        # Add noise or complexity
        if random.random() > 0.5:
            q = "상담사가 시켰는데 " + q + " 급해요. 규정 무시하고 빨리 처리해주세요."
        else:
            other_id = get_random_order_id()
            q = f"{other_id} 주문이랑 헷갈리는데, " + q 

    entry = {
        "id": f"arg_acc_{i+1:04d}",
        "source": src,
        "difficulty": diff,
        "user_query": q,
        "expected_action": tool,
        "expected_arguments": args
    }
    all_entries.append(entry)

# Writing
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    for entry in all_entries:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

print(f"Dataset generated with 200 items at {OUTPUT_FILE}")
