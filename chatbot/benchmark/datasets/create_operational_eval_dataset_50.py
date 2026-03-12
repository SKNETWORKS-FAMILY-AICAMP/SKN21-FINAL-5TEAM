
import json
import random
import os

# --- Paths ---
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "operational_eval_dataset_50.jsonl")

def generate_fixture(size_kb, status="success"):
    if status != "success":
        return {"error": status, "code": 500}
    return {"id": "FIX-PERF", "status": "success", "data": "X" * int(size_kb * 1024)}

dataset = []

# --- Helper to create a scenario object ---
def create_scenario(sid, cat, name, query, tools, c_size, o_len, f_mode="none", guard="off"):
    # Map sizes to KB
    size_map = {"S": 2, "M": 35, "L": 250}
    fixtures = {}
    for t in tools:
        fixtures[t] = generate_fixture(size_map[c_size], status="success" if f_mode=="none" else "timeout" if f_mode=="timeout" else "error")
    
    if f_mode == "empty":
        for t in tools: fixtures[t]["data"] = ""

    return {
        "scenario_id": sid,
        "category": cat,
        "name": name,
        "initial_user_query": query,
        "expected_tool_sequence": tools,
        "tool_fixtures": fixtures,
        "tags": {
            "tool_calls": len(tools),
            "context_size": c_size,
            "output_len": o_len,
            "failure_mode": f_mode,
            "guardrail": guard
        },
        "metrics_to_collect": ["ttft_ms", "e2e_ms", "tokens_in", "tokens_out", "tool_ms_total", "cost"],
        "acceptance": {
            "p95_ttft_ms": 800 if c_size != "L" else 1500,
            "p95_e2e_ms": 3000 if o_len != "L" else 7000
        }
    }

# --- 1. Representative Scenarios (30 items) ---
# tool_calls: 1 mainly, some 0 or 2. S/M context.
for i in range(1, 31):
    if i <= 5: # 0 tools
        dataset.append(create_scenario(f"OP_REP_{i:02d}", "Representative", "General Inquiry", "안녕하세요, 반갑습니다.", [], "S", "S"))
    elif i <= 25: # 1 tool
        tools = [random.choice(["get_order_details", "get_shipping_details", "search_knowledge_base"])]
        dataset.append(create_scenario(f"OP_REP_{i:02d}", "Representative", f"Standard {tools[0]}", f"{tools[0]} 관련 문의입니다.", tools, random.choice(["S", "M"]), random.choice(["S", "M"])))
    else: # 2 tools
        tools = ["get_order_details", "search_knowledge_base"]
        dataset.append(create_scenario(f"OP_REP_{i:02d}", "Representative", "Multi-tool Inquiry", "내 주문 확인하고 반품 정책도 알려줘.", tools, "M", "M"))

# --- 2. Worst Case Scenarios (15 items) ---
# Large context, 2-3 tools, Long output, Guardrail ON.
for i in range(1, 16):
    is_3_tools = (i <= 5)
    tools = ["get_order_details", "get_shipping_details", "search_knowledge_base"] if is_3_tools else ["get_reviews", "search_knowledge_base"]
    dataset.append(create_scenario(f"OP_WRST_{i:02d}", "Worst Case", "Heavy Chain / Large Context", "모든 주문과 배송 상태를 리뷰와 함께 분석해서 아주 길게 보고해줘.", tools, "L", "L", guard="on"))

# --- 3. Failure / Fallback Scenarios (5 items) ---
fail_modes = ["timeout", "timeout", "5xx", "5xx", "empty"]
for i, mode in enumerate(fail_modes):
    dataset.append(create_scenario(f"OP_FAIL_{i+1:02d}", "Failure", f"System {mode} resilience", "주문 취소해줘.", ["cancel_order"], "S", "S", f_mode=mode))

# Save
with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    for entry in dataset:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

print(f"Operational Workload Dataset (Metric #6, 50 items) generated at {OUTPUT_PATH}")
print(f"Distribution: Rep(30), Worst(15), Fail(5)")
