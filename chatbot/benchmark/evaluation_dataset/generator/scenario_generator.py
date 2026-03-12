"""
Scenario Generator
실제 DB 데이터 기반 테스트 시나리오 자동 생성
"""

import json
import random
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.models import Order, Product, User, ShippingAddress
from chatbot.src.infrastructure.openai import get_openai_client


class ScenarioGenerator:
    """실제 DB 데이터 기반 시나리오 생성기"""

    def __init__(self, db: Session):
        self.db = db
        self.client = get_openai_client()

        # 템플릿 로드
        template_dir = Path(__file__).parent.parent / "templates"
        with open(template_dir / "intent_templates.json") as f:
            self.intent_templates = json.load(f)
        with open(template_dir / "entity_variations.json") as f:
            self.entity_variations = json.load(f)
        with open(template_dir / "conversation_flows.json") as f:
            self.conversation_flows = json.load(f)

        # 실제 데이터 캐시
        self._cache_real_data()

    def _cache_real_data(self):
        """실제 DB 데이터 캐싱"""
        self.real_orders = self.db.query(Order).limit(100).all()
        self.real_products = self.db.query(Product).limit(50).all()
        self.real_users = self.db.query(User).limit(20).all()
        self.real_addresses = self.db.query(ShippingAddress).limit(30).all()

        print(f"✅ 실제 데이터 캐싱 완료:")
        print(f"   - 주문: {len(self.real_orders)}개")
        print(f"   - 상품: {len(self.real_products)}개")
        print(f"   - 사용자: {len(self.real_users)}개")
        print(f"   - 배송지: {len(self.real_addresses)}개")

    # ============================================
    # 단일 턴 시나리오 생성
    # ============================================

    def generate_single_turn_scenarios(
        self, intent: str, count: int = 30, use_real_data: bool = True
    ) -> List[Dict[str, Any]]:
        """
        단일 턴 시나리오 생성

        Args:
            intent: 의도 (order_lookup, cancel_order 등)
            count: 생성할 샘플 수
            use_real_data: 실제 DB 데이터 사용 여부
        """
        scenarios = []

        if intent not in self.intent_templates:
            print(f"⚠️  Unknown intent: {intent}")
            return scenarios

        template_data = self.intent_templates[intent]
        base_templates = template_data["templates"]
        tools = template_data["tools"]

        for i in range(count):
            # 베이스 템플릿 선택
            base_template = random.choice(base_templates)

            # 엔티티 채우기
            filled_template = self._fill_entities(base_template, intent, use_real_data)

            # LLM으로 자연스러운 변형 생성
            variations = self._generate_variations_with_llm(
                filled_template, intent, num_variations=1
            )

            # 시나리오 생성
            for variation in variations:
                scenario = {
                    "input": variation,
                    "intent": intent,
                    "expected_tool": random.choice(tools) if tools else None,
                    "expected_output": {"intent": intent, "tools": tools},
                    "metadata": {
                        "type": "single_turn",
                        "template": base_template,
                        "use_real_data": use_real_data,
                    },
                }
                scenarios.append(scenario)

        return scenarios

    def _fill_entities(self, template: str, intent: str, use_real_data: bool) -> str:
        """템플릿의 엔티티를 실제 데이터로 채우기"""
        filled = template

        # {order_id} 채우기
        if "{order_id}" in filled:
            if use_real_data and self.real_orders:
                order = random.choice(self.real_orders)
                order_id = order.order_number
            else:
                order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1, 999):03d}"
            filled = filled.replace("{order_id}", order_id)

        # {product_name} 채우기
        if "{product_name}" in filled:
            if use_real_data and self.real_products:
                product = random.choice(self.real_products)
                product_name = product.name
            else:
                brands = ["나이키", "아디다스", "자라"]
                items = ["티셔츠", "청바지", "스니커즈"]
                product_name = f"{random.choice(brands)} {random.choice(items)}"
            filled = filled.replace("{product_name}", product_name)

        # {date} 채우기
        if "{date}" in filled:
            date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime(
                "%Y-%m-%d"
            )
            filled = filled.replace("{date}", date)

        # {n} 채우기 (수량 등)
        if "{n}" in filled:
            n = str(random.randint(1, 10))
            filled = filled.replace("{n}", n)

        return filled

    def _generate_variations_with_llm(
        self, template: str, intent: str, num_variations: int = 3
    ) -> List[str]:
        """
        LLM을 사용하여 자연스러운 표현 변형 생성
        """
        prompt = f"""당신은 한국 이커머스 챗봇 테스트 데이터를 생성하는 전문가입니다.

주어진 템플릿 문장을 {num_variations}가지 다른 방식으로 표현해주세요.
의도는 같지만 표현을 자연스럽고 다양하게 바꿔주세요.

**템플릿**: {template}
**의도**: {intent}

**요구사항**:
1. 실제 사용자가 쓸 법한 자연스러운 표현
2. 격식체/반말 혼용
3. 오타나 줄임말 포함 가능
4. 문맥은 동일하게 유지
5. 각 변형은 한 줄로 작성

**출력 형식** (JSON):
{{"variations": ["변형1", "변형2", "변형3"]}}
"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 한국어 데이터 생성 전문가입니다.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.9,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            return result.get("variations", [template])

        except Exception as e:
            print(f"⚠️  LLM 생성 실패: {e}")
            return [template]

    # ============================================
    # 멀티턴 시나리오 생성
    # ============================================

    def generate_multi_turn_scenarios(
        self, flow_name: str, count: int = 10, use_real_data: bool = True
    ) -> List[Dict[str, Any]]:
        """
        멀티턴 대화 시나리오 생성
        """
        scenarios = []

        if flow_name not in self.conversation_flows:
            print(f"⚠️  Unknown flow: {flow_name}")
            return scenarios

        flow_template = self.conversation_flows[flow_name]

        for i in range(count):
            # 실제 데이터 선택 (일관성 유지)
            if use_real_data and self.real_orders:
                order = random.choice(self.real_orders)
                context_data = {
                    "order_id": order.order_number,
                    "product_name": order.items[0].product_option.product.name
                    if order.items
                    else "상품",
                    "user_id": order.user_id,
                }
            else:
                context_data = {
                    "order_id": f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1, 999):03d}",
                    "product_name": "테스트 상품",
                    "user_id": 1,
                }

            # 각 턴 생성
            turns = []
            for turn_template in flow_template["turns"]:
                # 템플릿 채우기
                user_message = turn_template["user"]
                for key, value in context_data.items():
                    user_message = user_message.replace(f"{{{key}}}", str(value))

                turn = {
                    "user": user_message,
                    "intent": turn_template["intent"],
                    "expected_tool": turn_template.get("expected_tool"),
                    "expected_ui_action": turn_template.get("expected_ui_action"),
                    "context_required": turn_template.get("context_required", []),
                    "validation_required": turn_template.get(
                        "validation_required", False
                    ),
                }
                turns.append(turn)

            scenario = {
                "flow_name": flow_name,
                "description": flow_template["description"],
                "turns": turns,
                "complexity": flow_template["complexity"],
                "context_data": context_data,
                "metadata": {
                    "type": "multi_turn",
                    "use_real_data": use_real_data,
                    "turn_count": len(turns),
                },
            }
            scenarios.append(scenario)

        return scenarios

    # ============================================
    # 도구 커버리지 기반 생성
    # ============================================

    def generate_tool_coverage_scenarios(
        self, tools: List[str], samples_per_tool: int = 20
    ) -> List[Dict[str, Any]]:
        """
        모든 도구를 커버하는 시나리오 생성

        Args:
            tools: 테스트할 도구 목록
            samples_per_tool: 도구당 샘플 수
        """
        scenarios = []

        # Intent -> Tools 매핑
        intent_tool_map = {}
        for intent, data in self.intent_templates.items():
            for tool in data["tools"]:
                if tool not in intent_tool_map:
                    intent_tool_map[tool] = []
                intent_tool_map[tool].append(intent)

        for tool in tools:
            if tool not in intent_tool_map:
                print(
                    f"⚠️  도구 '{tool}'에 대한 템플릿이 없습니다. GPT로 자동 생성 중..."
                )
                # GPT로 템플릿 자동 생성
                auto_template = self._auto_generate_tool_template(tool)
                if auto_template:
                    # 동적으로 intent_templates에 추가
                    generated_intent = f"auto_{tool}"
                    self.intent_templates[generated_intent] = auto_template
                    intent_tool_map[tool] = [generated_intent]

                    # 파일에도 저장 (다음 실행시 재사용)
                    self._save_auto_template(generated_intent, auto_template)
                    print(f"   ✅ '{tool}' 템플릿 자동 생성 완료")
                else:
                    print(f"   ❌ '{tool}' 템플릿 생성 실패")
                    continue

            # 해당 도구를 사용하는 intent 선택
            intents = intent_tool_map[tool]

            for intent in intents:
                # 각 intent별로 샘플 생성
                tool_scenarios = self.generate_single_turn_scenarios(
                    intent=intent,
                    count=samples_per_tool // len(intents),
                    use_real_data=True,
                )

                # 도구 명시
                for scenario in tool_scenarios:
                    scenario["target_tool"] = tool
                    scenario["metadata"]["coverage_target"] = tool

                scenarios.extend(tool_scenarios)

        return scenarios

    def _auto_generate_tool_template(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        GPT를 사용해서 도구의 템플릿 자동 생성

        Args:
            tool_name: 도구 이름

        Returns:
            생성된 템플릿 (intent_templates 형식)
        """
        try:
            # nodes_v2.py에서 실제 도구 객체 가져오기
            from chatbot.src.graph.nodes_v2 import TOOLS

            tool_obj = None
            for t in TOOLS:
                if hasattr(t, "name") and t.name == tool_name:
                    tool_obj = t
                    break

            if not tool_obj:
                return None

            # 도구 정보 추출
            tool_description = (
                tool_obj.description if hasattr(tool_obj, "description") else ""
            )
            tool_args = str(tool_obj.args) if hasattr(tool_obj, "args") else ""

            # GPT 프롬프트
            prompt = f"""당신은 전자상거래 챗봇 테스트 데이터 생성 전문가입니다.

다음 도구에 대한 테스트 시나리오를 생성해주세요:

도구 이름: {tool_name}
설명: {tool_description}
파라미터: {tool_args}

요구사항:
1. 한국어로 자연스러운 사용자 질문 5개 생성
2. 다양한 표현 사용 (존댓말/반말, 짧은 문장/긴 문장)
3. 실제 사용자가 할 법한 질문

JSON 형식으로 응답:
{{
    "examples": ["질문1", "질문2", "질문3", "질문4", "질문5"],
    "tools": ["{tool_name}"]
}}
"""

            response = self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.8,
            )

            result = json.loads(response.choices[0].message.content)

            # 기존 intent_templates 형식에 맞게 변환
            template = {
                "templates": result.get("examples", []),  # examples → templates
                "tools": result.get("tools", [tool_name]),
            }
            return template

        except Exception as e:
            print(f"   ⚠️  GPT 템플릿 생성 실패: {e}")
            return None

    def _save_auto_template(self, intent_name: str, template: Dict[str, Any]):
        """
        자동 생성된 템플릿을 intent_templates.json에 저장
        """
        try:
            template_file = (
                Path(__file__).parent.parent / "templates" / "intent_templates.json"
            )

            # 기존 템플릿 읽기
            with open(template_file, "r", encoding="utf-8") as f:
                templates = json.load(f)

            # 새 템플릿 추가
            templates[intent_name] = template

            # 파일에 저장
            with open(template_file, "w", encoding="utf-8") as f:
                json.dump(templates, f, ensure_ascii=False, indent=2)

            print(f"   💾 '{intent_name}' 템플릿을 파일에 저장했습니다")

        except Exception as e:
            print(f"   ⚠️  템플릿 파일 저장 실패: {e}")

    # ============================================
    # 엣지 케이스 생성
    # ============================================

    def generate_edge_case_scenarios(self, count: int = 50) -> List[Dict[str, Any]]:
        """
        엣지 케이스 시나리오 생성
        """
        scenarios = []

        edge_cases = [
            # 존재하지 않는 데이터
            {
                "input": "주문번호 INVALID-999 취소해줘",
                "intent": "cancel_order",
                "expected_error": "order_not_found",
                "category": "invalid_data",
            },
            {
                "input": "주문번호 없는거 조회해줘",
                "intent": "order_lookup",
                "expected_error": "order_not_found",
                "category": "invalid_data",
            },
            # 모호한 요청
            {
                "input": "그거",
                "intent": "ambiguous",
                "expected_response": "clarification_needed",
                "category": "ambiguous",
            },
            {
                "input": "취소",
                "intent": "cancel_order",
                "expected_response": "request_order_info",
                "category": "ambiguous",
            },
            # 빈 입력
            {
                "input": "",
                "intent": "empty",
                "expected_response": "ask_for_input",
                "category": "empty",
            },
            {
                "input": "   ",
                "intent": "empty",
                "expected_response": "ask_for_input",
                "category": "empty",
            },
            # 매우 긴 입력
            {
                "input": "주문 " + "취소 " * 100,
                "intent": "cancel_order",
                "expected_response": "handle_long_input",
                "category": "extreme_length",
            },
            # 특수문자
            {
                "input": "주문@@##$$취소",
                "intent": "cancel_order",
                "expected_response": "parse_special_chars",
                "category": "special_chars",
            },
            # 동시 다중 요청
            {
                "input": "주문 취소하고 포인트 조회하고 배송지도 바꿔줘",
                "intent": "multi_action",
                "expected_response": "handle_multiple_intents",
                "category": "multi_intent",
            },
            # 부정적 표현
            {
                "input": "주문 취소 안돼?",
                "intent": "cancel_order",
                "expected_tool": "cancel_order",
                "category": "negative_expression",
            },
            {
                "input": "포인트 없어?",
                "intent": "points_inquiry",
                "expected_tool": "get_user_points",
                "category": "negative_expression",
            },
            # 오타
            {
                "input": "주문 추회",  # 조회 오타
                "intent": "order_lookup",
                "expected_tool": "get_order_list",
                "category": "typo",
            },
            {
                "input": "츄소",  # 취소 오타
                "intent": "cancel_order",
                "expected_response": "handle_typo",
                "category": "typo",
            },
        ]

        # LLM으로 추가 엣지 케이스 생성
        llm_edge_cases = self._generate_edge_cases_with_llm(count - len(edge_cases))

        for i, case in enumerate(edge_cases + llm_edge_cases):
            scenario = {
                "input": case["input"],
                "intent": case.get("intent", "unknown"),
                "expected_tool": case.get("expected_tool"),
                "expected_error": case.get("expected_error"),
                "expected_response": case.get("expected_response"),
                "metadata": {
                    "type": "edge_case",
                    "category": case.get("category", "unknown"),
                    "difficulty": "hard",
                },
            }
            scenarios.append(scenario)

        return scenarios[:count]

    def _generate_edge_cases_with_llm(self, count: int) -> List[Dict[str, Any]]:
        """LLM으로 추가 엣지 케이스 생성"""
        prompt = f"""이커머스 챗봇의 엣지 케이스 {count}개를 생성해주세요.

**엣지 케이스 유형**:
1. 모호한 요청 (지시대명사만 사용)
2. 오타가 많은 입력
3. 문맥이 빠진 요청
4. 이상한 순서의 정보
5. 과도하게 긴 입력
6. 중복된 요청

**출력 형식** (JSON):
{{
  "edge_cases": [
    {{
      "input": "사용자 입력",
      "intent": "예상 의도",
      "category": "엣지케이스 유형",
      "expected_response": "예상 처리 방식"
    }}
  ]
}}
"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": "당신은 챗봇 테스트 전문가입니다."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.9,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            return result.get("edge_cases", [])

        except Exception as e:
            print(f"⚠️  LLM 엣지케이스 생성 실패: {e}")
            return []

    # ============================================
    # 전체 데이터셋 생성
    # ============================================

    def generate_complete_dataset(
        self, config: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        완전한 평가 데이터셋 생성

        Args:
            config: 생성 설정
                {
                    "single_turn_per_intent": 30,
                    "multi_turn_per_flow": 10,
                    "edge_cases": 50,
                    "use_real_data": True
                }
        """
        print("📊 평가 데이터셋 생성 시작...")

        dataset = {"functional_test": [], "conversation_test": [], "edge_case_test": []}

        # 1. 단일 턴 (기능 테스트)
        print("\n1️⃣  단일 턴 시나리오 생성...")
        for intent in self.intent_templates.keys():
            scenarios = self.generate_single_turn_scenarios(
                intent=intent,
                count=config.get("single_turn_per_intent", 30),
                use_real_data=config.get("use_real_data", True),
            )
            dataset["functional_test"].extend(scenarios)
            print(f"   ✓ {intent}: {len(scenarios)}개")

        # 2. 멀티턴 (대화 테스트)
        print("\n2️⃣  멀티턴 시나리오 생성...")
        for flow_name in self.conversation_flows.keys():
            scenarios = self.generate_multi_turn_scenarios(
                flow_name=flow_name,
                count=config.get("multi_turn_per_flow", 10),
                use_real_data=config.get("use_real_data", True),
            )
            dataset["conversation_test"].extend(scenarios)
            print(f"   ✓ {flow_name}: {len(scenarios)}개")

        # 3. 엣지 케이스
        print("\n3️⃣  엣지 케이스 생성...")
        edge_scenarios = self.generate_edge_case_scenarios(
            count=config.get("edge_cases", 50)
        )
        dataset["edge_case_test"].extend(edge_scenarios)
        print(f"   ✓ 엣지 케이스: {len(edge_scenarios)}개")

        # 통계
        total = sum(len(v) for v in dataset.values())
        print(f"\n✅ 생성 완료!")
        print(f"   📈 총 시나리오: {total}개")
        print(f"   - 기능 테스트: {len(dataset['functional_test'])}개")
        print(f"   - 대화 테스트: {len(dataset['conversation_test'])}개")
        print(f"   - 엣지 케이스: {len(dataset['edge_case_test'])}개")

        return dataset

    def save_dataset(
        self,
        dataset: Dict[str, List[Dict[str, Any]]],
        output_dir: str = "ecommerce/chatbot/benchmark/evaluation_dataset/output",
    ):
        """데이터셋 저장"""
        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for name, scenarios in dataset.items():
            if scenarios:
                filepath = output_path / f"{name}_{timestamp}.jsonl"
                with open(filepath, "w", encoding="utf-8") as f:
                    for scenario in scenarios:
                        f.write(json.dumps(scenario, ensure_ascii=False) + "\n")
                print(f"💾 {name}: {filepath} ({len(scenarios)}개)")


# ============================================
# CLI 실행
# ============================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="평가 데이터셋 생성")
    parser.add_argument(
        "--single-turn", type=int, default=30, help="Intent당 단일턴 샘플 수"
    )
    parser.add_argument(
        "--multi-turn", type=int, default=10, help="Flow당 멀티턴 샘플 수"
    )
    parser.add_argument("--edge-cases", type=int, default=50, help="엣지 케이스 수")
    parser.add_argument(
        "--no-real-data", action="store_true", help="실제 DB 데이터 미사용"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="ecommerce/chatbot/benchmark/evaluation_dataset/output",
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        generator = ScenarioGenerator(db)

        config = {
            "single_turn_per_intent": args.single_turn,
            "multi_turn_per_flow": args.multi_turn,
            "edge_cases": args.edge_cases,
            "use_real_data": not args.no_real_data,
        }

        dataset = generator.generate_complete_dataset(config)
        generator.save_dataset(dataset, output_dir=args.output)

    finally:
        db.close()
