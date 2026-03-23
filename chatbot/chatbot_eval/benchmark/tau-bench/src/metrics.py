"""
metrics.py

tau-bench 평가 지표 계산 모듈.
Pass@k, Task Success Rate 등 표준 tau-bench 메트릭을 구현합니다.
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from datetime import datetime


def compute_pass_at_k(results_per_task: dict[str, list[bool]], k: int) -> float:
    """
    Pass@k를 계산합니다.

    모든 태스크에 대해 k번의 시도 중 적어도 1번 성공할 확률의 평균입니다.

    Parameters:
        results_per_task: {task_id: [성공여부, ...]} — 각 태스크별 시도 결과 리스트
        k: 시도 횟수 상한

    Returns:
        Pass@k 값 (0.0 ~ 1.0)
    """
    if not results_per_task:
        return 0.0

    pass_at_k_values = []
    for task_id, results in results_per_task.items():
        n = len(results)
        c = sum(results)  # 성공 횟수
        if n == 0:
            continue
        if k >= n:
            # 모든 시도를 사용하는 경우
            p = 1.0 - (math.comb(n - c, min(k, n - c)) / math.comb(n, min(k, n))) if n >= k else (1.0 if c > 0 else 0.0)
        else:
            # 정확히 k번 시도하는 경우
            p = 1.0 - math.comb(n - c, k) / math.comb(n, k) if n >= k and (n - c) >= k else (1.0 if c > 0 else 0.0)
        pass_at_k_values.append(p)

    return sum(pass_at_k_values) / len(pass_at_k_values) if pass_at_k_values else 0.0


def compute_task_success_rate(eval_results: list[dict]) -> dict:
    """
    태스크별, 카테고리별 성공률을 계산합니다.

    Parameters:
        eval_results: 평가 결과 딕셔너리 리스트

    Returns:
        성공률 통계 딕셔너리
    """
    if not eval_results:
        return {}

    total = len(eval_results)
    success_count = sum(1 for r in eval_results if r.get("success", False))

    # 카테고리별 집계
    category_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "success": 0})
    for result in eval_results:
        cat = result.get("category", "unknown")
        category_stats[cat]["total"] += 1
        if result.get("success", False):
            category_stats[cat]["success"] += 1

    category_rates = {
        cat: {
            "total": stats["total"],
            "success": stats["success"],
            "rate": stats["success"] / stats["total"] if stats["total"] > 0 else 0.0
        }
        for cat, stats in category_stats.items()
    }

    # 도구 호출 통계
    tool_call_pass_count = sum(1 for r in eval_results if r.get("tool_call_pass", False))
    state_pass_count = sum(1 for r in eval_results if r.get("state_pass", False))
    avg_turns = sum(r.get("turn_count", 0) for r in eval_results) / total if total > 0 else 0.0

    return {
        "total_tasks": total,
        "success_count": success_count,
        "task_success_rate": success_count / total if total > 0 else 0.0,
        "tool_call_pass_rate": tool_call_pass_count / total if total > 0 else 0.0,
        "state_pass_rate": state_pass_count / total if total > 0 else 0.0,
        "avg_turns_per_task": round(avg_turns, 2),
        "category_breakdown": category_rates,
    }


def compute_pass_at_k_from_results(
    eval_results: list[dict], k_values: list[int] = None
) -> dict[str, float]:
    """
    평가 결과 리스트에서 여러 k 값에 대한 Pass@k를 계산합니다.

    Parameters:
        eval_results: 평가 결과 딕셔너리 리스트 (run_idx 포함 가정)
        k_values: 계산할 k 값 목록 (기본값: [1, 4, 8])

    Returns:
        {f"pass@{k}": 값, ...} 딕셔너리
    """
    if k_values is None:
        k_values = [1, 4, 8]

    # task_id별로 시도 결과 집계
    results_per_task: dict[str, list[bool]] = defaultdict(list)
    for result in eval_results:
        task_id = result.get("task_id", "unknown")
        results_per_task[task_id].append(result.get("success", False))

    return {
        f"pass@{k}": round(compute_pass_at_k(results_per_task, k), 4)
        for k in k_values
    }


def save_metrics(
    eval_results: list[dict],
    model_name: str,
    output_dir: Path,
    task_type: str = "eval",
    k_values: list[int] = None,
) -> dict:
    """
    평가 지표를 계산하고 JSON 파일로 저장합니다.

    Parameters:
        eval_results: 전체 평가 결과 리스트
        model_name: 평가 대상 모델 이름
        output_dir: 결과 저장 디렉토리
        task_type: 태스크 유형 이름 (파일명에 사용)
        k_values: Pass@k의 k 값 목록

    Returns:
        저장된 지표 딕셔너리
    """
    if k_values is None:
        k_values = [1, 4, 8]

    task_success = compute_task_success_rate(eval_results)
    pass_at_k = compute_pass_at_k_from_results(eval_results, k_values)

    metrics = {
        "model": model_name,
        "task_type": task_type,
        "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_success": task_success,
        "pass_at_k": pass_at_k,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    score_path = output_dir / f"{task_type}_eval_score.json"

    # 기존 결과 로드 후 누적
    existing: list[dict] = []
    if score_path.exists():
        try:
            with open(score_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 기존 파일이 단일 객체(이전 형식)인 경우 리스트로 변환
            if isinstance(data, dict):
                existing = [data]
            elif isinstance(data, list):
                existing = data
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(metrics)

    with open(score_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)

    print(f"  ✓ 지표 저장 완료 (누적 {len(existing)}회): {score_path}")
    return metrics


def print_metrics_summary(metrics: dict) -> None:
    """평가 지표 요약을 콘솔에 출력합니다."""
    ts = metrics.get("task_success", {})
    pk = metrics.get("pass_at_k", {})

    print("\n" + "=" * 55)
    print(f"  τ-Bench 평가 결과 — {metrics.get('model', 'unknown')}")
    print("=" * 55)
    print(f"  Task Success Rate : {ts.get('task_success_rate', 0) * 100:.1f}%  "
          f"({ts.get('success_count', 0)}/{ts.get('total_tasks', 0)})")
    print(f"  Tool Call Pass    : {ts.get('tool_call_pass_rate', 0) * 100:.1f}%")
    print(f"  State Pass        : {ts.get('state_pass_rate', 0) * 100:.1f}%")
    print(f"  Avg Turns/Task    : {ts.get('avg_turns_per_task', 0)}")
    print()
    for k_label, val in pk.items():
        print(f"  {k_label:<10}: {val * 100:.1f}%")
    print()
    print("  카테고리별 성공률:")
    for cat, stats in ts.get("category_breakdown", {}).items():
        print(f"    {cat:<20}: {stats['rate'] * 100:.1f}%  ({stats['success']}/{stats['total']})")
    print("=" * 55)
