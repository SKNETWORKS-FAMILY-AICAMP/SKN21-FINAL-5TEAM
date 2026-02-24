"""
Quality Tools
데이터셋 품질 체크
"""
import json
from typing import List, Dict, Any, Set
from collections import Counter, defaultdict
from pathlib import Path


class QualityChecker:
    """데이터셋 품질 체크"""
    
    @staticmethod
    def check_duplicates(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """중복 체크"""
        inputs = [s.get("input", "") for s in samples]
        input_counts = Counter(inputs)
        duplicates = {inp: count for inp, count in input_counts.items() if count > 1}
        
        return {
            "total_samples": len(samples),
            "unique_samples": len(set(inputs)),
            "duplicate_count": len(duplicates),
            "duplicate_rate": len(duplicates) / len(samples) if samples else 0,
            "duplicates": duplicates
        }
    
    @staticmethod
    def check_diversity(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """다양성 체크"""
        intents = [s.get("intent", "unknown") for s in samples]
        intent_dist = Counter(intents)
        
        # Intent별 샘플 수
        min_count = min(intent_dist.values()) if intent_dist else 0
        max_count = max(intent_dist.values()) if intent_dist else 0
        
        # 균형도 (표준편차 기반)
        counts = list(intent_dist.values())
        mean = sum(counts) / len(counts) if counts else 0
        variance = sum((c - mean) ** 2 for c in counts) / len(counts) if counts else 0
        std_dev = variance ** 0.5
        
        balance_score = 1.0 - min(std_dev / mean, 1.0) if mean > 0 else 0
        
        return {
            "intent_distribution": dict(intent_dist),
            "unique_intents": len(intent_dist),
            "min_samples_per_intent": min_count,
            "max_samples_per_intent": max_count,
            "balance_score": balance_score,
            "verdict": "BALANCED" if balance_score > 0.7 else "IMBALANCED"
        }
    
    @staticmethod
    def check_coverage(
        samples: List[Dict[str, Any]],
        required_intents: List[str],
        required_tools: List[str]
    ) -> Dict[str, Any]:
        """커버리지 체크"""
        sample_intents = set(s.get("intent") for s in samples)
        sample_tools = set()
        
        for s in samples:
            if "tools" in s:
                sample_tools.update(s["tools"])
            if "expected_tool" in s:
                sample_tools.add(s["expected_tool"])
        
        intent_coverage = len(sample_intents & set(required_intents)) / len(required_intents) if required_intents else 0
        tool_coverage = len(sample_tools & set(required_tools)) / len(required_tools) if required_tools else 0
        
        return {
            "intent_coverage": intent_coverage,
            "tool_coverage": tool_coverage,
            "missing_intents": list(set(required_intents) - sample_intents),
            "missing_tools": list(set(required_tools) - sample_tools),
            "verdict": "COMPLETE" if intent_coverage == 1.0 and tool_coverage == 1.0 else "INCOMPLETE"
        }
    
    @staticmethod
    def analyze_dataset(
        dataset_path: str,
        required_intents: List[str] = None,
        required_tools: List[str] = None
    ) -> Dict[str, Any]:
        """전체 품질 분석"""
        # 데이터 로드
        samples = []
        with open(dataset_path) as f:
            for line in f:
                samples.append(json.loads(line))
        
        print(f"📊 데이터셋 품질 분석: {len(samples)}개 샘플")
        
        # 체크 실행
        duplicate_check = QualityChecker.check_duplicates(samples)
        diversity_check = QualityChecker.check_diversity(samples)
        
        coverage_check = {}
        if required_intents or required_tools:
            coverage_check = QualityChecker.check_coverage(
                samples,
                required_intents or [],
                required_tools or []
            )
        
        # 종합 판정
        issues = []
        if duplicate_check["duplicate_rate"] > 0.1:
            issues.append(f"높은 중복률: {duplicate_check['duplicate_rate']:.1%}")
        if diversity_check["balance_score"] < 0.7:
            issues.append(f"불균형: {diversity_check['balance_score']:.2f}")
        if coverage_check.get("intent_coverage", 1.0) < 1.0:
            issues.append(f"Intent 커버리지 부족: {coverage_check['intent_coverage']:.1%}")
        
        overall_quality = "GOOD" if not issues else "NEEDS_IMPROVEMENT"
        
        return {
            "dataset_path": dataset_path,
            "total_samples": len(samples),
            "duplicate_check": duplicate_check,
            "diversity_check": diversity_check,
            "coverage_check": coverage_check,
            "issues": issues,
            "overall_quality": overall_quality
        }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", type=str)
    args = parser.parse_args()
    
    result = QualityChecker.analyze_dataset(args.dataset)
    
    print("\n" + "="*50)
    print(f"품질: {result['overall_quality']}")
    print(f"중복률: {result['duplicate_check']['duplicate_rate']:.1%}")
    print(f"균형도: {result['diversity_check']['balance_score']:.2f}")
    if result.get("coverage_check"):
        print(f"Intent 커버리지: {result['coverage_check']['intent_coverage']:.1%}")
    
    if result["issues"]:
        print("\n⚠️  개선 필요:")
        for issue in result["issues"]:
            print(f"  - {issue}")
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
