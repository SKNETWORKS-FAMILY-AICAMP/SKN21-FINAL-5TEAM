"""
Dataset Generator Runner
평가 데이터셋 자동 생성 실행
"""
import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from ecommerce.chatbot.benchmark.evaluation_dataset.generator.scenario_generator import ScenarioGenerator
from ecommerce.chatbot.benchmark.evaluation_dataset.generator.variation_generator import VariationGenerator
from ecommerce.chatbot.benchmark.evaluation_dataset.generator.adversarial_generator import AdversarialGenerator
from ecommerce.chatbot.benchmark.quality_tools.quality_checker import QualityChecker

class DatasetBuilder:
    """평가 데이터셋 자동 생성 파이프라인"""
    
    def __init__(self, db_session):
        self.scenario_gen = ScenarioGenerator(db_session)
        self.variation_gen = VariationGenerator()
        self.adversarial_gen = AdversarialGenerator()
        self.quality_checker = QualityChecker()
        
    def generate_full_dataset(
        self,
        output_dir: str = "ecommerce/chatbot/benchmark/datasets",
        config: Dict[str, Any] = None
    ) -> Dict[str, Path]:
        """전체 데이터셋 생성"""
        
        config = config or {
            "functional": {"enabled": True, "samples_per_tool": 30},
            "conversation": {"enabled": True, "multi_turn_scenarios": 20},
            "security": {"enabled": True, "attack_samples": 50},
            "variations": {"enabled": True, "per_sample": 3}
        }
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        generated_files = {}
        
        print("🚀 평가 데이터셋 자동 생성 시작\n")
        
        # 1. 기능 테스트 데이터셋
        if config["functional"]["enabled"]:
            print("1️⃣ 기능 테스트 데이터셋 생성...")
            functional_data = self._generate_functional_dataset(
                config["functional"]["samples_per_tool"]
            )
            
            # 변형 생성
            if config["variations"]["enabled"]:
                functional_data = self._apply_variations(
                    functional_data,
                    config["variations"]["per_sample"]
                )
            
            functional_path = output_path / f"functional_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
            self._save_dataset(functional_data, functional_path)
            generated_files["functional"] = functional_path
            print(f"   ✅ {len(functional_data)}개 샘플 생성 → {functional_path}\n")
        
        # 2. 대화 흐름 데이터셋
        if config["conversation"]["enabled"]:
            print("2️⃣ 대화 흐름 데이터셋 생성...")
            conversation_data = self._generate_conversation_dataset(
                config["conversation"]["multi_turn_scenarios"]
            )
            
            conversation_path = output_path / f"conversation_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
            self._save_dataset(conversation_data, conversation_path)
            generated_files["conversation"] = conversation_path
            print(f"   ✅ {len(conversation_data)}개 대화 시나리오 → {conversation_path}\n")
        
        # 3. 보안 테스트 데이터셋
        if config["security"]["enabled"]:
            print("3️⃣ 보안 테스트 데이터셋 생성...")
            security_data = self._generate_security_dataset(
                config["security"]["attack_samples"]
            )
            
            security_path = output_path / f"security_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
            self._save_dataset(security_data, security_path)
            generated_files["security"] = security_path
            print(f"   ✅ {len(security_data)}개 보안 테스트 → {security_path}\n")
        
        # 4. 품질 체크
        print("4️⃣ 데이터셋 품질 검증...")
        for name, path in generated_files.items():
            print(f"   검증 중: {name}...")
            quality_report = self.quality_checker.analyze_dataset(str(path))
            
            report_path = path.parent / f"{path.stem}_quality_report.json"
            with open(report_path, 'w') as f:
                json.dump(quality_report, f, ensure_ascii=False, indent=2)
            
            print(f"   ✅ 품질: {quality_report['overall_quality']}")
        
        print("\n🎉 데이터셋 생성 완료!")
        return generated_files
    
    def _generate_functional_dataset(self, samples_per_tool: int) -> List[Dict[str, Any]]:
        """기능 테스트 데이터셋"""
        samples = []
        
        # 모든 intent에 대해 시나리오 생성
        for intent in self.scenario_gen.intent_templates.keys():
            single_turn = self.scenario_gen.generate_single_turn_scenarios(
                intent=intent,
                count=samples_per_tool
            )
            samples.extend(single_turn)
        
        # 모든 도구에 대해 커버리지 시나리오 생성
        tools = list(set(
            tool for intent_data in self.scenario_gen.intent_templates.values()
            for tool in intent_data.get("tools", [])
        ))
        tool_coverage = self.scenario_gen.generate_tool_coverage_scenarios(
            tools=tools,
            samples_per_tool=samples_per_tool
        )
        samples.extend(tool_coverage)
        
        # 엣지 케이스
        edge_cases = self.scenario_gen.generate_edge_case_scenarios(count=samples_per_tool)
        samples.extend(edge_cases)
        
        return samples
    
    def _generate_conversation_dataset(self, num_scenarios: int) -> List[Dict[str, Any]]:
        """대화 흐름 데이터셋"""
        samples = []
        
        # 모든 대화 flow에 대해 시나리오 생성
        flows = list(self.scenario_gen.conversation_flows.keys())
        scenarios_per_flow = max(1, num_scenarios // len(flows)) if flows else 0
        
        for flow_name in flows:
            flow_scenarios = self.scenario_gen.generate_multi_turn_scenarios(
                flow_name=flow_name,
                count=scenarios_per_flow
            )
            samples.extend(flow_scenarios)
        
        return samples
    
    def _generate_security_dataset(self, attack_samples: int) -> List[Dict[str, Any]]:
        """보안 테스트 데이터셋"""
        samples = []
        
        samples_per_type = attack_samples // 5
        
        samples.extend(self.adversarial_gen.generate_prompt_injection_tests(samples_per_type))
        samples.extend(self.adversarial_gen.generate_jailbreak_tests(samples_per_type))
        samples.extend(self.adversarial_gen.generate_authorization_bypass_tests(samples_per_type))
        samples.extend(self.adversarial_gen.generate_pii_extraction_tests(samples_per_type))
        samples.extend(self.adversarial_gen.generate_malicious_input_tests(samples_per_type))
        
        return samples
    
    def _apply_variations(
        self,
        samples: List[Dict[str, Any]],
        variations_per_sample: int
    ) -> List[Dict[str, Any]]:
        """변형 적용"""
        varied_samples = []
        
        for sample in samples:
            # 원본 추가
            varied_samples.append(sample)
            
            # intent 추출 (없으면 기본값 사용)
            intent = sample.get("intent", "general")
            
            # 변형 생성
            variations = self.variation_gen.generate_variations(
                original_text=sample["input"],
                intent=intent,
                num_variations=variations_per_sample
            )
            
            for variation in variations:
                varied_sample = sample.copy()
                varied_sample["input"] = variation.get("input", sample["input"])
                varied_sample["variation_type"] = variation.get("variation_type", "unknown")
                varied_samples.append(varied_sample)
        
        return varied_samples
    
    def _save_dataset(self, samples: List[Dict[str, Any]], path: Path):
        """데이터셋 저장 (JSONL)"""
        with open(path, 'w') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')


def main():
    """실행 예시"""
    from ecommerce.platform.backend.app.database import SessionLocal
    
    db = SessionLocal()
    
    try:
        builder = DatasetBuilder(db)
        
        # 전체 데이터셋 생성
        generated = builder.generate_full_dataset(
            config={
                "functional": {"enabled": True, "samples_per_tool": 30},
                "conversation": {"enabled": True, "multi_turn_scenarios": 20},
                "security": {"enabled": True, "attack_samples": 50},
                "variations": {"enabled": True, "per_sample": 2}
            }
        )
        
        print("\n📁 생성된 파일:")
        for name, path in generated.items():
            print(f"   {name}: {path}")
            
    finally:
        db.close()


if __name__ == "__main__":
    main()
