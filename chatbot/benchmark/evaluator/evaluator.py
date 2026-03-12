"""
Evaluator
챗봇 평가 자동 실행
"""
import json
from typing import List, Dict, Any
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

from chatbot.benchmark.evaluator.metrics import EvaluationMetrics
from ecommerce.chatbot.src.graph.workflow import graph_app


class ChatbotEvaluator:
    """챗봇 평가 실행기"""
    
    def __init__(self, user_context: Dict[str, Any] = None):
        self.metrics = EvaluationMetrics()
        self.user_context = user_context or {
            "user_info": {"id": 1, "name": "테스트유저"},
            "is_authenticated": True
        }
    
    def evaluate_single_sample(
        self,
        sample: Dict[str, Any]
    ) -> Dict[str, Any]:
        """단일 샘플 평가"""
        try:
            # 챗봇 실행
            state = {
                **self.user_context,
                "messages": [{"role": "user", "content": sample["input"]}]
            }
            
            result = graph_app.invoke(state)
            
            # 예측 결과 추출
            prediction = self._extract_prediction(result)
            
            # 평가
            scores = self.metrics.comprehensive_evaluation(prediction, sample)
            
            return {
                "sample": sample,
                "prediction": prediction,
                "scores": scores,
                "passed": scores["overall_score"] >= 0.7
            }
            
        except Exception as e:
            return {
                "sample": sample,
                "error": str(e),
                "passed": False
            }
    
    def _extract_prediction(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """결과에서 예측 추출"""
        messages = result.get("messages", [])
        last_message = messages[-1] if messages else None
        
        return {
            "intent": result.get("nlu_result", {}).get("intent"),
            "entities": result.get("nlu_result", {}).get("entities", {}),
            "tools": [call.get("name") for msg in messages if hasattr(msg, "tool_calls") for call in msg.tool_calls],
            "response": last_message.content if last_message else ""
        }
    
    def evaluate_dataset(
        self,
        dataset_path: str,
        output_path: str = None
    ) -> Dict[str, Any]:
        """데이터셋 전체 평가"""
        # 데이터 로드
        samples = []
        with open(dataset_path, 'r') as f:
            for line in f:
                samples.append(json.loads(line))
        
        print(f"📊 {len(samples)}개 샘플 평가 시작...")
        
        # 평가 실행
        results = []
        for sample in tqdm(samples):
            result = self.evaluate_single_sample(sample)
            results.append(result)
        
        # 통계 계산
        stats = self._calculate_stats(results)
        
        # 저장
        if output_path:
            self._save_results(results, stats, output_path)
        
        return {
            "results": results,
            "stats": stats
        }
    
    def _calculate_stats(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """통계 계산"""
        total = len(results)
        passed = sum(1 for r in results if r.get("passed", False))
        
        avg_scores = {}
        score_keys = ["intent_accuracy", "overall_score"]
        
        for key in score_keys:
            scores = [r["scores"].get(key, 0) for r in results if "scores" in r]
            avg_scores[key] = sum(scores) / len(scores) if scores else 0
        
        return {
            "total_samples": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0,
            "average_scores": avg_scores
        }
    
    def _save_results(
        self,
        results: List[Dict[str, Any]],
        stats: Dict[str, Any],
        output_path: str
    ):
        """결과 저장"""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        # 상세 결과
        with open(output, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "stats": stats,
                "results": results
            }, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 결과 저장: {output}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    
    evaluator = ChatbotEvaluator()
    evaluator.evaluate_dataset(args.dataset, args.output)
