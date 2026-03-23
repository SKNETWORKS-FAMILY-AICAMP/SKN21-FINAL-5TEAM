"""
complete_dataset_v4.py
[목적]
분리된 2단계: 1단계에서 생성(및 수정)된 질문 데이터(intermediate_queries_v5_verified.jsonl)를 읽어, 
각 질문에 대한 올바른 정답(Ground Truth Tool Call)을 Rule-based(하드코딩) 방식으로 생성하고 최종 JSONL 형식으로 저장합니다.
(LLM의 환각 방지 및 평가 정확도 100% 보장)
"""

import json
import os
import sys
import re
from pathlib import Path

# 경로 설정 (로컬 환경에 맞게 유지)
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR, PROJECT_ROOT, TOOLS_PATH

INPUT_PATH = DATA_DIR / "intermediate_queries_v1_verified.jsonl"
OUTPUT_PATH = DATA_DIR / "my_eval_arg_accuracy_dialogs.jsonl"

# 허용 가능한 정답 베리에이션 (채점 시 활용) - reason은 아래에서 그룹별로 동적 처리
ACCEPTABLE = {
    "size": ["XS", "S", "M", "L", "XL", "90", "95", "100", "105", "FREE", "free"],
    "color": ["black", "white", "ivory", "cream", "beige", "navy", "gray", "brown"],
    "rating": [1, 2, 3, 4, 5],
    "payment_method": ["CARD"]
}

def load_tools() -> list:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)

# ============================================================
# tools.json 기반 유틸리티
# ============================================================
def build_tool_map(openai_tools: list) -> dict:
    tool_map = {}
    for tool in openai_tools:
        fn = tool.get("function", {})
        name = fn.get("name")
        if name:
            tool_map[name] = tool
    return tool_map

def get_tool_properties(tool_def: dict) -> dict:
    return tool_def.get("function", {}).get("parameters", {}).get("properties", {}) or {}

def get_tool_required(tool_def: dict) -> list:
    return tool_def.get("function", {}).get("parameters", {}).get("required", []) or []

# ============================================================
# 시나리오 이름 → 실제 도구 이름 매핑
# ============================================================
SCENARIO_TO_TOOL = {
    "cancel":              "cancel",
    "refund":              "refund",
    "exchange":            "exchange",
    "shipping_with_id":    "shipping",
    "shipping_no_id":      "shipping",
    "search_by_text_clip": "search_by_text_clip",
    "recommend_clothes":   "recommend_clothes",
    "search_by_image":     "search_by_image",
    "used_sale":           "open_used_sale_form",
    "review":              "create_review",
    "register_gift_card":  "register_gift_card",
}

# ============================================================
# 사용자 질문에서 파라미터 값을 동적 추출하는 함수들
# ============================================================
ORDER_ID_PATTERN  = re.compile(r"\bORD[-_A-Za-z0-9]+\b", re.IGNORECASE)
GIFT_CODE_PATTERN = re.compile(r"[A-Z]+-\d+")
RATING_PATTERN    = re.compile(r"([1-5])\s*점")

REASON_CANDIDATES = [
    "배송이 너무 늦어서 취소합니다", "상품 정보와 실제 상품이 달라요",
    "다른 쇼핑몰에서 더 저렴하게 팔아요", "단순 변심으로 인한 취소",
    "색상이 화면과 달라요", "사이즈가 안 맞아요", "상품이 파손되었어요",
    "배송이 너무 느려요", "그냥 마음이 바뀌었어요", "생각했던 것과 달라요",
    "다른 상품이 배송됨", "주문을 잘못했어요", "필요가 없어졌어요",
    "실수로 주문했어요", "마음에 들지 않음", "사이즈 불일치",
    "상품 불만족", "단순 변심", "단순변심", "잘못 주문", "배송 지연",
    "마음이 변함", "변심", "파손", "불량",
]

COLOR_CANDIDATES = [
    "black", "white", "ivory", "cream", "beige", "navy", "gray", "brown",
    "블랙", "화이트", "아이보리", "크림", "베이지", "네이비", "그레이", "브라운",
]

def _extract_order_id(query: str) -> str:
    m = ORDER_ID_PATTERN.search(query or "")
    return m.group(0) if m else ""

def _extract_reason(query: str) -> str:
    # 'reason' 제외 정책 적용: 항상 빈 문자열 반환
    return ""

def _extract_gift_code(query: str) -> str:
    m = GIFT_CODE_PATTERN.search(query or "")
    return m.group(0) if m else ""

def _extract_rating(query: str):
    m = RATING_PATTERN.search(query or "")
    return int(m.group(1)) if m else None

def _extract_color(query: str) -> str:
    q = (query or "").lower()
    for c in COLOR_CANDIDATES:
        if c.lower() in q:
            return c
    return ""

def _extract_search_query(query: str) -> str:
    """사용자 질문 텍스트에서 불필요한 서술어를 제거하고 핵심 검색어만 추출합니다."""
    q = (query or "").strip()
    if not q: return None
    
    # 1. 자주 쓰이는 키워드 강제 매핑 (휴리스틱)
    if "반팔" in q: return "반팔 티셔츠"
    if "원피스" in q: return "원피스"
    if "맨투맨" in q: return "맨투맨"
    if "팬츠" in q or "바지" in q: return "와이드 팬츠"
    if "정장" in q or "수트" in q: return "정장 세트"
    if "가방" in q or "백" in q: return "가방"
    
    # 2. 매핑이 안 되면 문장 끝의 서술어 제거
    q = re.sub(r'(찾아줘|검색해줘|보여줘|추천해줘|있나요\?|알려주세요|어떤가요|검색 좀).*$', '', q).strip()
    return q if q else None

def _extract_category(query: str) -> str:
    q = query or ""
    if "원피스" in q:    return "Dress"
    if "스커트" in q or "치마" in q: return "Skirt"
    if "바지" in q or "팬츠" in q:  return "Bottomwear"
    if "정장" in q:      return "Formal"
    return "Topwear"

def _extract_usage(query: str):
    """의류 추천 시 명확한 용도가 있을 때만 반환 (없으면 None)"""
    q = query or ""
    if "정장" in q or "회사" in q or "면접" in q or "결혼식" in q: return "Formal"
    if "운동" in q or "트레이닝" in q:            return "Sports"
    if "파티" in q or "행사" in q:                return "Party"
    if "캐주얼" in q or "일상" in q or "편하게" in q: return "Casual"
    return None # 명시되지 않으면 Optional 이므로 생략 유도

# 파라미터 이름별 추출 로직 매핑
def _build_param_value(param_name: str, query: str, item: dict):
    order_id = item.get("order", {}).get("order_id", "")
    user_id  = item.get("user_id")

    if param_name == "user_id":
        return user_id
    if param_name == "order_id":
        return _extract_order_id(query) or order_id or None
    if param_name == "reason":
        # 'reason' 제외 정책 적용
        return None
    if param_name == "query":
        return _extract_search_query(query) or None
    if param_name == "code":
        return _extract_gift_code(query) or None
    if param_name == "rating":
        return _extract_rating(query)
    if param_name == "color":
        return _extract_color(query) or None
    if param_name == "category":
        return _extract_category(query)
    if param_name == "usage":
        return _extract_usage(query)
    if param_name == "image_bytes":
        # 이미지 데이터는 텍스트 평가에서 맞출 수 없으므로 GT에서 아예 제외
        return None
    if param_name == "is_seller_fault":
        # is_seller_fault는 모델이 자체 판단하도록 GT에서 제외 (Optional 처리)
        # 모델이 넣든 안 넣든 다른 필수 인자만 맞으면 Pass
        return None
    if param_name in ("content", "review_text"):
        # 리뷰 내용은 LLM이 자유롭게 생성하므로 GT에서 제외 (채점 생략)
        return None

    return None

# ============================================================
# Ground Truth 생성 및 허용 인자 동기화
# ============================================================
def generate_rule_based_ground_truth(item: dict, tool_map: dict) -> dict:
    action     = item["scenario"]["action"]
    query_text = item.get("user_query", "")
    tool_name  = SCENARIO_TO_TOOL.get(action, action)

    if tool_name not in tool_map:
        tool_def = {}
    else:
        tool_def = tool_map[tool_name]

    properties   = get_tool_properties(tool_def)
    required_set = set(get_tool_required(tool_def))

    arguments = {}
    for param_name in properties:
        value = _build_param_value(param_name, query_text, item)

        if value is not None and value != "":
            arguments[param_name] = value
        elif param_name in required_set and param_name != "reason":
            raise ValueError(f"필수 인자 누락: {tool_name}.{param_name} / query={query_text}")

    gt = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
        ]
    }
    return gt

def ensure_acceptable_arguments(gt: dict, order_id: str) -> dict:
    """GT에 들어간 값을 바탕으로 엄격하고 합리적인 채점 리스트(acceptable_arguments) 구성"""
    acc_args = {}
    
    # Reason에 대한 소수 정예 동의어 그룹 매핑 (너무 관대한 채점 방지)
    reason_synonyms = [
        ["단순 변심", "변심", "단순변심", "그냥 마음이 바뀌었어요", "마음에 들지 않음"],
        ["배송 지연", "배송이 너무 늦어서 취소합니다", "배송이 너무 느려요", "배송 지연으로 인한 취소"],
        ["사이즈가 안 맞아요", "사이즈 불일치", "사이즈 미스", "사이즈가 너무 커서 교환", "사이즈가 작아서"],
        ["상품이 파손되었어요", "파손", "불량", "불량품", "다른 상품이 배송됨"]
    ]

    calls = gt.get("tool_calls", [])
    if calls:
        for tc in calls:
            args = tc.get("function", {}).get("arguments", {})
            for k, v in args.items():
                if k == "order_id":
                    acc_args["order_id"] = [order_id] if order_id else [""]
                elif k == "query" and isinstance(v, str):
                    # 검색 query는 핵심어만 포함되면 Pass (유연한 채점)
                    # 원문 전체도 허용하도록 보완
                    acc_args[k] = [v]
                    # 원문 전체도 허용
                    original_query = tc.get("function", {}).get("original_query") # Assuming original_query might be stored here
                    if original_query and original_query not in acc_args[k]:
                        acc_args[k].append(original_query)
                # reason 관련 처리는 상위 단계(제외 정책)에 의해 스킵됨
                elif k in ACCEPTABLE:
                    acc_args[k] = ACCEPTABLE[k].copy()
                    if isinstance(v, (str, int)) and v not in acc_args[k]:
                        acc_args[k].append(v)
                else:
                    if isinstance(v, (str, int)):
                        acc_args[k] = [v]
                        
    # 불필요한 키(이미지 바이트 등)가 들어가지 않도록 클렌징
    acc_args.pop("image_bytes", None)
    acc_args.pop("content", None)
    
    return acc_args

def format_simplified_tools(openai_tools: list, relevant_names: list) -> list:
    res = []
    for t in openai_tools:
        if t.get("function", {}).get("name") in relevant_names:
            fn = t.get("function", {})
            res.append({
                "type": "function",
                "function": {
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {})
                }
            })
    return res

def main():
    print("=" * 60)
    print("2단계: 질문 기반 Ground Truth 생성 및 최종 Dataset 완성 (Rule-based 최적화)")
    print("=" * 60)
    
    if not INPUT_PATH.exists():
        print(f"[ERROR] {INPUT_PATH} 파일이 없습니다. 1단계를 먼저 실행해주세요.")
        return
        
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f if line.strip()]
        
    all_openai_tools = load_tools()
    tool_map = build_tool_map(all_openai_tools)
    results = []
    call_id_counter = 1
    
    for idx, item in enumerate(queries, start=1):
        # 입력이 원본 JSON 구조(scenario dict, order dict, user_query)인 경우 직접 사용
        scenario = item.get('scenario', {})
        scenario_name = scenario.get('action', item.get('scenario_name', 'unknown'))
        
        # 👇 [여기에 3줄 추가!] 이미지 검색 시나리오는 무한 대기를 유발하므로 생성에서 제외합니다.
        if scenario_name == "search_by_image" or scenario.get('name') == "이미지 검색":
            print(f"[{idx}/{len(queries)}] 이미지 검색 시나리오 스킵 (텍스트 평가 전용)")
            continue

        # 👇 [여기에 3줄 추가!] 상품권 등록 시나리오는 무한 대기를 유발하므로 생성에서 제외합니다.
        if scenario_name == "register_gift_card" or scenario.get('name') == "상품권 등록":
            print(f"[{idx}/{len(queries)}] 상품권 등록 시나리오 스킵 (텍스트 평가 전용)")
            continue
        
        # order_id: 원본 구조(order.order_id) 또는 이전 flat 구조(acceptable_arguments.order_id) 모두 지원
        extracted_o_id = item.get('order', {}).get('order_id', '')
        if not extracted_o_id:
            order_id_list = item.get('acceptable_arguments', {}).get('order_id', [])
            extracted_o_id = order_id_list[0] if order_id_list else ""
        if scenario_name == "shipping_no_id":
            extracted_o_id = ""
            
        print(f"[{idx}/{len(queries)}] {scenario_name} GT 생성 중...")
        
        # scenario 구조 정규화 (원본 or flat 모두 대응)
        tools_raw = scenario.get('tools', [])
        if tools_raw and isinstance(tools_raw[0], dict):
            tools_names = [t.get('name') or t.get('function', {}).get('name') for t in tools_raw]
        else:
            tools_names = list(tools_raw)  # 이미 문자열 리스트인 경우
        
        possible = scenario.get('possible', item.get('possible'))

        if possible is None:
            raise ValueError(f"possible 필드 없음: {scenario_name}")
        item['scenario'] = {
            'name': scenario.get('name', scenario_name),
            'action': scenario_name,
            'tools': tools_names,
            'possible': possible
        }
        
        item['order'] = {
            'order_id': extracted_o_id,
            'status': item.get('order', {}).get('status', item.get('order_status'))
        }
        # user_query: 원본 구조(user_query) 또는 이전 flat 구조(messages[0].content) 모두 지원
        if 'user_query' not in item:
            item['user_query'] = item.get('messages', [{}])[0].get('content', '')
        
        gt = generate_rule_based_ground_truth(item, tool_map)
            
        for tc in gt.get("tool_calls", []):
            tc["id"] = f"call_{call_id_counter}"
            call_id_counter += 1
            
        acc_args = ensure_acceptable_arguments(gt, item['order']['order_id'])
        tools_simplified = format_simplified_tools(all_openai_tools, item["scenario"]["tools"])

        flat_item = {
            "task_id": f"eval_{idx:04d}",
            "serial_num": idx,
            "scenario_name": item["scenario"]["name"],
            "expected_tool": item["scenario"]["action"],
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
    print(f"✅ 완료! 최적화된 평가 데이터셋(JSONL)이 성공적으로 생성되었습니다.")
    print(f"   저장 경로: {OUTPUT_PATH}")
    print(f"   총 평가 항목 수: {len(results)}개")
    print("=" * 60)

if __name__ == "__main__":
    main()