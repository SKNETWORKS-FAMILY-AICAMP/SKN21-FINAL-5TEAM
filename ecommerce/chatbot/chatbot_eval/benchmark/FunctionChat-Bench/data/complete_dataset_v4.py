"""
complete_dataset_v4.py
[목적]
분리된 2단계: 1단계에서 생성(및 수정)된 질문 데이터(intermediate_queries_v4.json)를 읽어, 
각 질문에 대한 올바른 정답(Ground Truth Tool Call)을 생성하고 최종 JSONL 형식으로 저장합니다.
"""

import json
import os
import sys
import re
from pathlib import Path
from dotenv import load_dotenv

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR, PROJECT_ROOT, TOOLS_PATH
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o-mini"
INPUT_PATH = DATA_DIR / "intermediate_queries_v4_verified.jsonl"
OUTPUT_PATH = DATA_DIR / "my_eval_arg_accuracy_dialogs3.jsonl"

ORDER_STATUS_POLICY = """
## 주문 상태 정책 (반드시 준수)
| 상태                   | 취소 | 반품/환불 | 교환       |
|------------------------|------|-----------|------------|
| PENDING (결제 대기)    | 불가 | 불가      | 불가       |
| PAID (결제 완료)       | 가능 | 불가→안내 | 가능(무료) |
| PREPARING (상품준비중) | 가능 | 불가→안내 | 가능(무료) |
| SHIPPED (배송중)       | 불가 | 가능      | 가능(유료) |
| DELIVERED 7일 이내     | 불가 | 가능      | 가능(유료) |
| DELIVERED 7일 초과     | 불가 | 불가      | 불가       |
"""

ACCEPTABLE = {
    "reason": [
        "단순 변심", "simple_change_of_mind", "change_of_mind", "customer_preference",
        "사이즈가 안 맞아요", "색상이 화면과 달라요", "배송이 너무 늦어서 취소합니다",
        "상품이 파손되었어요", "다른 상품이 배송됨", "마음에 들지 않음",
        "그냥 마음이 바뀌었어요", "배송이 너무 느려요", "주문을 잘못했어요",
        "필요가 없어졌어요", "다른 쇼핑몰에서 더 저렴하게 팔아요",
        "상품 정보와 실제 상품이 달라요", "생각했던 것과 달라요",
        "실수로 주문했어요", "변심", "단순변심", "잘못 주문", "배송 지연",
        "마음이 변함", "단순 변심으로 인한 취소", "사이즈 불일치", "상품 불만족"
    ],
    "size": ["XS", "S", "M", "L", "XL", "90", "95", "100", "105", "FREE", "free"],
    "color": ["black", "white", "ivory", "cream", "beige", "navy", "gray", "brown"],
    "rating": [1, 2, 3, 4, 5],
    "payment_method": ["카드", "계좌이체", "CARD", "BANK_TRANSFER", "카카오페이", "네이버페이"]
}

def load_tools() -> list:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)

def simplify_tool(tool_def: dict) -> dict:
    func = tool_def.get("function", {})
    return {
        "name": func.get("name"),
        "description": func.get("description"),
        "parameters": func.get("parameters", {}).get("properties", {}),
        "required": func.get("parameters", {}).get("required", [])
    }

def get_gt_system_prompt(user_id: int) -> str:
    return f"""당신은 이커머스 챗봇 평가용 데이터셋 전문가입니다.
사용자 질문(Query)을 보고, 챗봇이 수행해야 할 올바른 정답(Ground Truth Tool Call)을 생성합니다.

{ORDER_STATUS_POLICY}

규칙:
1. output은 순수 JSON 객체(마크다운 블록 제외)만 반환합니다.
2. 모든 tool call에는 user_id: {user_id} 파라미터를 반드시 포함해야 합니다.
3. [중요] 사용자가 주문번호 및 필수 인자를 제공한 경우 즉시 해당 액션 툴을 호출합니다.
4. [핵심] 불가능한 주문 상태라도 텍스트로 미리 거절하지 말고 상태 검증을 위해 'shipping' 툴을 활용하세요.
5. [핵심] 주문번호가 주어지지 않은 상태에서 주문 목록이나 배송 조회를 요청하면, `shipping`이 아닌 `get_user_orders`를 호출하여 주문 목록을 먼저 띄워야 합니다.
6. [매우 중요] 사용자 발화에 직접 언급되지 않은 선택적 파라미터(예: limit, days, action_context, new_option_id, product_id, image_bytes 등)는 절대 임의의 값이나 빈 문자열("")로 채워넣지 마세요. 스키마에 required가 아니라면 파라미터 자체를 생략(제외)하세요.
"""

def generate_ground_truth(item: dict, all_tools: list) -> dict:
    scenario = item["scenario"]
    order = item["order"]
    tools_in_scenario = scenario["tools"]
    action_possible = "가능" if scenario["possible"] else "불가능"
    
    simplified_tools = [simplify_tool(t) for t in all_tools if t.get("function", {}).get("name") in tools_in_scenario]
    tools_str = json.dumps(simplified_tools, ensure_ascii=False, indent=2)

    prompt = f"""
다음 사용자 질문을 처리하기 위해 챗봇이 호출해야 할 적절한 함수를 찾고 인자(arguments)를 추출하여 반환하세요.
(함수 인자에 필요한 값을 사용자 질문에서 추출. 없을 경우 빈 값 또는 기본값 사용)

시나리오 이름: {scenario['name']}
주문 상태: {order['status'].upper()}
해당 시나리오 가능 여부: {action_possible}

사용자 질문:
"{item['user_query']}"

사용 가능한 도구(Tools) 명세서:
{tools_str}

반환 포맷 예시:
{{
  "ground_truth": {{
    "role": "assistant",
    "content": null,
    "tool_calls": [
      {{
        "type": "function",
        "function": {{
          "name": "cancel",
          "arguments": {{
            "order_id": "{order['order_id']}",
            "user_id": {item['user_id']},
            "reason": "단순 변심"
          }}
        }}
      }}
    ]
  }}
}}
"""
    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": get_gt_system_prompt(item["user_id"])},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        ).choices[0].message.content.strip()
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        return json.loads(raw).get("ground_truth", {})
    except Exception as e:
        print(f"[ERROR] GT 생성 에러: {e}")
        return {}

def ensure_acceptable_arguments(gt: dict, order_id: str) -> dict:
    acc_args = {}
    calls = gt.get("tool_calls", [])
    if calls:
        for tc in calls:
            args = tc.get("function", {}).get("arguments", {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {}
                
            for k, v in args.items():
                if k in ACCEPTABLE and k != "order_id":
                    acc_args[k] = ACCEPTABLE[k].copy()
                    
                    # [이슈 1 해결] LLM이 생성한 정답(v)이 허용 리스트에 없으면 강제 추가
                    if isinstance(v, (str, int)) and v not in acc_args[k]:
                        acc_args[k].append(v)
                        
            if "order_id" in args:
                if not order_id:  # shipping_no_id 처리
                    acc_args["order_id"] = [""]
                else:
                    acc_args["order_id"] = [order_id]
    return acc_args

def format_simplified_tools(openai_tools: list, relevant_names: list) -> list:
    res = []
    for t in openai_tools:
        if t.get("function", {}).get("name") in relevant_names:
            fn = t.get("function", {})
            
            # OpenAI 표준 parameters 스키마(type, properties, required 등)를 훼손하지 않고 원본 그대로 넘김
            res.append({
                "name": fn.get("name"),
                "description": fn.get("description", ""), # description도 모델이 도구를 이해하는 데 필수적이므로 포함
                "parameters": fn.get("parameters", {})
            })
    return res

def main():
    print("=" * 60)
    print("2단계: 질문 기반 Ground Truth 생성 및 최종 Dataset 완성")
    print("=" * 60)
    
    if not INPUT_PATH.exists():
        print(f"[ERROR] {INPUT_PATH} 파일이 없습니다. 1단계를 먼저 실행해주세요.")
        return
        
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f if line.strip()]
        
    all_openai_tools = load_tools()
    results = []
    call_id_counter = 1
    
    for idx, item in enumerate(queries, start=1):
        print(f"[{idx}/{len(queries)}] {item.get('scenario_name')} (주문: {item.get('acceptable_arguments', {}).get('order_id', [''])[0]}) GT 생성 중...")
        
        # reconstruct scenario & order for generate_ground_truth compatibility
        item['scenario'] = {
            'name': item.get('scenario_name'),
            'action': item.get('scenario_name'),
            'tools': [t['name'] for t in item.get('tools', [])],
            'possible': True # assuming true
        }
        
        order_id_list = item.get('acceptable_arguments', {}).get('order_id', [])
        extracted_o_id = order_id_list[0] if order_id_list else ""
        if item.get('scenario_name') == "shipping_no_id":
            extracted_o_id = ""
            
        item['order'] = {
            'order_id': extracted_o_id,
            'status': 'paid' # default
        }
        item['user_query'] = item.get('messages', [{}])[0].get('content', '')
        
        gt = generate_ground_truth(item, all_openai_tools)
        if not gt:
            print(f"  -> 실패 건너뜀")
            continue
            
        # 순차 id 부여
        for tc in gt.get("tool_calls", []):
            if "type" not in tc: tc["type"] = "function"
            tc["id"] = f"call_{call_id_counter}"
            call_id_counter += 1
            
        acc_args = ensure_acceptable_arguments(gt, item['order']['order_id'])
        tools_simplified = format_simplified_tools(all_openai_tools, item["scenario"]["tools"])

        flat_item = {
            "task_id": f"eval_{idx:04d}",
            "serial_num": idx,
            "scenario_name": item["scenario"]["action"],
            "user_id": item["user_id"],
            "user_email": item["user_email"],
            "tools": tools_simplified,
            "messages": [{"role": "user", "content": item["user_query"]}],
            "ground_truth": gt,
            "acceptable_arguments": acc_args,
            "type_of_output": "call",
            "prediction": {"tool_calls": None}
        }
        results.append(flat_item)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for it in results:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
            
    print("\n" + "=" * 60)
    print(f"✅ 2단계 완료! 최종 평가 데이터셋(JSONL)이 성공적으로 생성되었습니다.")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print(f"   총 평가 항목 수: {len(results)}개")
    print("=" * 60)

if __name__ == "__main__":
    main()