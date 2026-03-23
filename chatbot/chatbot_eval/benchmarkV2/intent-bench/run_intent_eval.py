"""
Supervisor 라우팅 평가 실행기.

supervisor_eval_dataset.jsonl을 로드하여 planner_node와 supervisor 라우팅 로직만 호출하고,
현재 chatbot 서버 아키텍처의 planner → supervisor 분기 결과를 평가합니다.

단일 의도만 평가하며, result.json에는 details 없이 메트릭만 누적 저장합니다.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
import torch
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── 경로 설정 ──────────────────────────────────────────────

BENCH_DIR = Path(__file__).resolve().parent
DATASET_PATH = BENCH_DIR / "supervisor_eval_dataset.jsonl"
_RESULT_BASE_DIR = BENCH_DIR.parent / "result"

# TaskIntent → 평가용 노드 이름 매핑
# supervisor.py의 _INTENT_TO_NODE 기반, order_entry → order_intent_router로 표기
INTENT_TO_NODE: dict[str, str] = {
    "ORDER_CS":             "order_intent_router",
    "SEARCH_SIMILAR_TEXT":  "discovery_subagent",
    "SEARCH_SIMILAR_IMAGE": "discovery_subagent",
    "POLICY_RAG":           "policy_rag_subagent",
    "REGISTER_USED_ITEM":   "form_action_subagent",
    "WRITE_REVIEW":         "form_action_subagent",
    "REGISTER_GIFT_CARD":   "form_action_subagent",
    "GENERAL_CHAT":         "final_generator",
}


def _find_project_root(start: Path, marker: str = ".env") -> Path:
    for parent in [start] + list(start.parents):
        if (parent / marker).exists():
            return parent
    return start.parents[4]


_PROJECT_ROOT = _find_project_root(BENCH_DIR)
sys.path.insert(0, str(_PROJECT_ROOT))
load_dotenv(_PROJECT_ROOT / ".env")

# ── 프로젝트 import (dotenv 로드 이후) ─────────────────────

import httpx  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from chatbot.src.core.config import settings  # noqa: E402
import chatbot.src.graph.llm_providers as _llm_providers  # noqa: E402
from chatbot.src.graph.nodes.planner import planner_node  # noqa: E402
from chatbot.src.graph.nodes.supervisor import route_after_supervisor, supervisor_node  # noqa: E402


# 평가 전체에서 단일 httpx 클라이언트 공유 (호출마다 새 클라이언트 생성 시 연결 누적으로 hang 발생)
_SHARED_HTTP_CLIENT = httpx.Client(
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=0),
    timeout=60.0,
)


def _make_vllm_llm_no_pool(model: str, temperature: float = 0) -> ChatOpenAI:
    """공유 httpx 클라이언트 사용 + 요청마다 모델 언로드 (VRAM 누적 방지)."""
    base_url = (settings.VLLM_BASE_URL or "").strip()
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=SecretStr(settings.VLLM_API_KEY or "EMPTY"),
        base_url=base_url,
        http_client=_SHARED_HTTP_CLIENT,
        request_timeout=120,
        max_tokens=256,
    )


_llm_providers.make_vllm_llm = _make_vllm_llm_no_pool

_DEFAULT_EVAL_USER = {
    "id": 1,
    "name": "Intent Eval User",
    "email": "intent-eval@example.com",
    "site_id": "site_a",
    "access_token": None,
}

_ORDER_ROUTE_ALIASES = {
    "order_entry",
    "order_intent_router",
    "cancel_subagent",
    "refund_subagent",
    "exchange_subagent",
    "shipping_subagent",
    "order_list_subagent",
}
# ── 데이터셋 로드 ─────────────────────────────────────────


def load_dataset(path: Path) -> list[dict]:
    """JSONL 데이터셋 로드."""
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


# ── Planner + Supervisor route-only 평가 ──────────────────


def restart_ollama(model: str, base_url: str = "http://localhost:11434") -> None:
    """Ollama 서버 프로세스를 완전히 재시작하여 누적된 메모리를 초기화합니다."""
    print("  [Ollama 재시작] 서버 종료 중...")
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "//F", "//IM", "ollama.exe", "//T"],
            capture_output=True,
        )
    else:
        # Mac/Linux
        subprocess.run(["pkill", "-f", "ollama"], capture_output=True)
    time.sleep(2)

    # 트레이 앱(ollama app.exe)이 자동으로 ollama.exe를 재시작함
    # 별도로 ollama serve를 실행하면 프로세스가 중복되어 충돌 발생
    print("  [Ollama 재시작] 트레이 앱 자동 재시작 대기 중...")

    # 서버가 준비될 때까지 대기 (최대 30초)
    for _ in range(30):
        try:
            requests.get(f"{base_url}/api/version", timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        print("  [Ollama 재시작 실패] 서버 응답 없음")
        return

    time.sleep(3)  # 안정화 대기
    print(f"  [Ollama 재시작 완료] 메모리 초기화됨")


def _build_eval_state(user_input: str, model: str, provider: str) -> dict:
    conversation_id = f"intent-eval-{uuid.uuid4().hex[:12]}"
    turn_id = f"turn-{uuid.uuid4().hex[:12]}"
    state = {
        "messages": [HumanMessage(content=user_input)],
        "pending_tasks": [],
        "completed_tasks": [],
        "current_active_task": None,
        "order_context": {},
        "search_context": {},
        "ui_action_required": None,
        "agent_results": {},
        "guardrail_passed": True,
        "user_info": dict(_DEFAULT_EVAL_USER),
        "llm_provider": provider,
        "llm_model": model,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "conversation_summary": None,
    }
    return state


def _normalize_routed_node(node_name: str) -> str:
    if node_name in _ORDER_ROUTE_ALIASES:
        return "order_intent_router"
    return node_name


def _predict_nodes_via_route_only(
    user_input: str,
    model: str,
    provider: str,
) -> list[str]:
    state = _build_eval_state(user_input, model, provider)

    planner_result = planner_node(state)
    state = {
        **state,
        **planner_result,
    }

    supervisor_result = supervisor_node(state)
    routed_state = {
        **state,
        **supervisor_result,
    }
    routed_node = route_after_supervisor(routed_state)
    return [_normalize_routed_node(routed_node)]


def predict_nodes(
    user_input: str,
    model: str = "gpt-4o-mini",
    provider: str = "openai",
) -> list[str]:
    """planner와 supervisor 라우팅 코드만 호출해 첫 분기 노드를 추출."""
    return _predict_nodes_via_route_only(user_input, model, provider)


# ── 샘플별 평가 ──────────────────────────────────────────


def evaluate_sample(
    sample: dict,
    predicted_nodes: list[str],
) -> bool:
    """예측 노드가 기대 노드와 일치하는지 반환."""
    exp_node = sample["expected_node"]
    pred_node = predicted_nodes[0] if predicted_nodes else "NONE"
    return pred_node == exp_node


# ── Confusion Matrix ────────────────────────────────────


def build_confusion(details: list[dict]) -> dict[str, dict[str, int]]:
    """confusion matrix 생성."""
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in details:
        expected = d["expected_node"]
        predicted = d["predicted_node"]
        matrix[expected][predicted] += 1
    return {k: dict(v) for k, v in matrix.items()}


# ── 메인 평가 루프 ────────────────────────────────────────


def run_evaluation(
    dataset_path: Path = DATASET_PATH,
    result_path: Path | None = None,
    model: str = "gpt-4o-mini",
    provider: str = "openai",
    num_samples: int | None = None,
    batch_size: int | None = None,
    parallel: int = 1,
    difficulty: str | None = None,
) -> dict:
    """전체 평가 실행."""
    if result_path is None:
        result_dir = _RESULT_BASE_DIR / "supervisor_eval"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / "result.json"

    samples = load_dataset(dataset_path)
    if difficulty:
        samples = [s for s in samples if s.get("difficulty") == difficulty]
    if num_samples:
        samples = samples[:num_samples]

    model_label = f"{provider}/{model}"
    print("=== Supervisor 라우팅 평가 시작 ===")
    print(f"  모델: {model_label}")
    if difficulty:
        print(f"  난이도 필터: {difficulty}")
    print(f"  샘플 수: {len(samples)}")
    if parallel > 1:
        print(f"  병렬 처리: {parallel}개씩")
    if batch_size and provider == "vllm":
        print(f"  배치 크기: {batch_size} (배치마다 Ollama 재시작)")
    print()

    details: list[dict] = []
    all_pred_nodes: list[str] = []
    all_exp_nodes: list[str] = []

    start_time = time.time()

    # 청크 단위로 병렬 처리
    for chunk_start in range(0, len(samples), parallel):
        chunk = samples[chunk_start:chunk_start + parallel]
        global_offset = chunk_start  # 전체 샘플 기준 인덱스 오프셋

        # Ollama 재시작 (vllm 사용 시)
        if provider == "vllm" and chunk_start > 0:
            if parallel > 1 or (batch_size and chunk_start % batch_size == 0):
                print(f"\n  [{chunk_start}개 처리 완료] Ollama 재시작 중...")
                restart_ollama(model)
                print()

        # local(Transformers) 사용 시 모델 누적 메모리 방지를 위해 대기 (필요 시)
        if provider == "local" and chunk_start > 0:
            # 로컬은 현재 프로세스 내에서 로드되므로 재시작이 어려움. 대신 gc.collect() 등 고려 가능.
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()

        # 청크 내 샘플을 병렬로 predict_nodes 호출
        chunk_results: list[tuple[int, dict, list[str]]] = []

        if parallel > 1:
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                future_to_idx = {}
                for j, sample in enumerate(chunk):
                    future = executor.submit(predict_nodes, sample["input"], model, provider)
                    future_to_idx[future] = (j, sample)

                for future in as_completed(future_to_idx):
                    j, sample = future_to_idx[future]
                    try:
                        predicted_nodes = future.result()
                    except Exception as e:
                        idx = global_offset + j + 1
                        print(f"  [{idx}/{len(samples)}] 오류: {e}")
                        predicted_nodes = ["final_generator"]
                    chunk_results.append((j, sample, predicted_nodes))

            # 원래 순서대로 정렬
            chunk_results.sort(key=lambda x: x[0])
        else:
            # 순차 처리 (기존 동작)
            for j, sample in enumerate(chunk):
                try:
                    predicted_nodes = predict_nodes(sample["input"], model, provider)
                except Exception as e:
                    idx = global_offset + j + 1
                    print(f"  [{idx}/{len(samples)}] 오류: {e}")
                    predicted_nodes = ["final_generator"]
                chunk_results.append((j, sample, predicted_nodes))

        # vllm(Ollama) 사용 시 청크 간 대기 (연결 리소스 고갈 방지)
        if provider in ["vllm", "local"]:
            time.sleep(0.5)

        # 결과 처리 및 출력
        for j, sample, predicted_nodes in chunk_results:
            idx = global_offset + j + 1
            correct = evaluate_sample(sample, predicted_nodes)

            pred_node = predicted_nodes[0] if predicted_nodes else "NONE"
            difficulty = sample.get("difficulty", "easy")
            all_pred_nodes.append(pred_node)
            all_exp_nodes.append(sample["expected_node"])

            details.append({
                "input": sample["input"],
                "predicted_node": pred_node,
                "expected_node": sample["expected_node"],
                "difficulty": difficulty,
                "correct": correct,
            })

            status = "O" if correct else "X"
            print(
                f"  [{idx}/{len(samples)}] {status}  "
                f"[{difficulty}] "
                f"기대: {sample['expected_node']}  예측: {pred_node}  "
                f"입력: {sample['input'][:50]}..."
            )

    elapsed = time.time() - start_time

    # ── 통계 계산 ──────────────────────────────────────────

    total = len(details)
    correct_total = sum(1 for d in details if d["correct"])

    # 난이도별 통계
    diff_stats: dict[str, dict] = {}
    for diff_level in ("easy", "hard"):
        diff_samples = [d for d in details if d.get("difficulty") == diff_level]
        if diff_samples:
            diff_correct = sum(1 for d in diff_samples if d["correct"])
            diff_stats[diff_level] = {
                "total": len(diff_samples),
                "correct": diff_correct,
                "accuracy": round(diff_correct / len(diff_samples), 4),
            }

    # 노드별 F1 (단일 샘플 기준)
    per_node_f1: dict = {}
    macro_f1 = 0.0
    if all_pred_nodes and all_exp_nodes:
        all_labels = sorted(set(all_pred_nodes + all_exp_nodes))
        for label in all_labels:
            tp = sum(1 for p, e in zip(all_pred_nodes, all_exp_nodes) if p == label and e == label)
            fp = sum(1 for p, e in zip(all_pred_nodes, all_exp_nodes) if p == label and e != label)
            fn = sum(1 for p, e in zip(all_pred_nodes, all_exp_nodes) if p != label and e == label)
            support = tp + fn
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            per_node_f1[label] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": support,
            }

        node_f1s = [v["f1"] for v in per_node_f1.values()]
        macro_f1 = sum(node_f1s) / len(node_f1s)
        per_node_f1["macro_avg"] = {
            "precision": round(sum(v["precision"] for v in per_node_f1.values() if "support" in v) / len(node_f1s), 4),
            "recall": round(sum(v["recall"] for v in per_node_f1.values() if "support" in v) / len(node_f1s), 4),
            "f1": round(macro_f1, 4),
        }

    # Confusion matrix
    confusion = build_confusion(details)

    # ── 결과 조립 ──────────────────────────────────────────

    result = {
        "model": model_label,
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "difficulty_filter": difficulty,
        "total_samples": total,
        "metrics": {
            "accuracy": round(correct_total / total, 4) if total else 0.0,
            "per_node_f1": per_node_f1,
            "macro_f1": round(macro_f1, 4),
            "confusion_matrix": confusion,
        },
        "difficulty_breakdown": diff_stats,
        "summary": {
            "total": total,
            "correct": correct_total,
        },
    }

    # 결과 누적 저장 (메트릭만)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if result_path.exists():
        with open(result_path, encoding="utf-8") as f:
            history = json.load(f)
    history.append(result)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    # 상세 예측 데이터 누적 저장 (result_data.json)
    result_data_path = result_path.parent / "result_data.json"
    result_data = {
        "model": model_label,
        "timestamp": result["timestamp"],
        "difficulty_filter": difficulty,
        "total_samples": total,
        "difficulty_breakdown": diff_stats,
        "details": details,
    }
    data_history: list[dict] = []
    if result_data_path.exists():
        with open(result_data_path, encoding="utf-8") as f:
            data_history = json.load(f)
    data_history.append(result_data)
    with open(result_data_path, "w", encoding="utf-8") as f:
        json.dump(data_history, f, ensure_ascii=False, indent=2)

    # ── 결과 출력 ──────────────────────────────────────────

    print(f"\n{'='*55}")
    print("=== Supervisor 라우팅 평가 결과 ===")
    print(f"{'='*55}")
    print(f"  모델: {model_label}")
    print(f"  소요 시간: {elapsed:.1f}초")
    print(f"\n  [라우팅 정확도]")
    print(f"    전체 정확도: {result['metrics']['accuracy']:.2%} ({correct_total}/{total})")
    print(f"    Macro F1: {macro_f1:.4f}")

    if diff_stats:
        print(f"\n  [난이도별 정확도]")
        for diff_level, stats in sorted(diff_stats.items()):
            print(f"    {diff_level}: {stats['accuracy']:.2%} ({stats['correct']}/{stats['total']})")

    if per_node_f1:
        print(f"\n  [노드별 F1]")
        for node, scores in sorted(per_node_f1.items()):
            if node == "macro_avg":
                continue
            print(
                f"    {node}: "
                f"P={scores['precision']:.3f} "
                f"R={scores['recall']:.3f} "
                f"F1={scores['f1']:.3f} "
                f"(n={scores.get('support', '-')})"
            )

    if confusion:
        print(f"\n  [Confusion Matrix]")
        all_nodes = sorted(set(
            list(confusion.keys()) +
            [p for row in confusion.values() for p in row.keys()]
        ))
        header = f"{'실제\\예측':>22s}"
        for n in all_nodes:
            header += f" {n[:14]:>14s}"
        print(f"    {header}")
        for actual in all_nodes:
            row = f"{actual[:14]:>22s}"
            for pred in all_nodes:
                count = confusion.get(actual, {}).get(pred, 0)
                row += f" {count:>14d}"
            print(f"    {row}")

    print(f"\n  결과 저장: {result_path}")
    print(f"  상세 데이터 저장: {result_data_path}")

    return result


# ── CLI ────────────────────────────────────────────────────


# 실행 예시:
#
# [기본 실행 (OpenAI)]
#   python run_intent_eval.py                                         # openai gpt-4o-mini (기본 모델)로 순차 평가
#   python run_intent_eval.py --model gpt-4o-mini                         # openai gpt-4o 모델로 순차 평가
#   python run_intent_eval.py --num-samples 20                       # 앞 20개 샘플만 평가
#
# [로컬 LLM (Ollama/vllm)]
#   python run_intent_eval.py --provider vllm                        # Ollama qwen3:0.6b (기본)로 순차 평가
#   python run_intent_eval.py --provider vllm --model qwen3:0.6b     # Ollama 모델 명시 지정
#   python run_intent_eval.py --provider vllm --batch-size 15        # 15개마다 Ollama 재시작 (VRAM 해제)
#
# [병렬 처리 (ThreadPoolExecutor, 최대 10)]
#   python run_intent_eval.py --parallel 10                          # OpenAI에 10개씩 동시 요청
#   python run_intent_eval.py --parallel 5 --num-samples 50          # 5개씩 병렬로 50개만 평가
#   python run_intent_eval.py --provider vllm --parallel 5           # Ollama에 5개씩 동시 요청, 매 청크 후 재시작
#
# [난이도 필터 (easy | hard)]
#   python run_intent_eval.py --difficulty easy                      # easy 질문만 평가
#   python run_intent_eval.py --difficulty hard                      # hard 질문만 평가
#   python run_intent_eval.py --difficulty hard --parallel 10        # hard 질문만 10개씩 병렬 평가


def main():
    parser = argparse.ArgumentParser(description="Supervisor 라우팅 평가 실행")
    parser.add_argument(
        "--provider", type=str, default="openai",
        help="LLM 프로바이더 (openai | vllm | local, 기본: openai)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="모델명 (기본: provider에 따라 자동 결정)",
    )
    parser.add_argument(
        "--dataset", type=str, default=None,
        help="평가 데이터셋 경로 (기본: supervisor_eval_dataset.jsonl)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="결과 저장 경로",
    )
    parser.add_argument(
        "--num-samples", type=int, default=None,
        help="평가할 샘플 수 (기본: 전체)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=20,
        help="vllm(Ollama) 사용 시 배치 크기 (기본: 20, 배치마다 VRAM 해제)",
    )
    parser.add_argument(
        "--parallel", type=int, default=1, choices=range(1, 11),
        help="병렬 처리 수 (기본: 1, 최대: 10)",
        metavar="[1-10]",
    )
    parser.add_argument(
        "--difficulty", type=str, default=None, choices=["easy", "hard"],
        help="난이도 필터 (easy | hard, 기본: 전체)",
    )
    args = parser.parse_args()

    # vllm 사용 시 Ollama 설정 고정
    if args.provider == "vllm":
        settings.VLLM_BASE_URL = "http://localhost:11434/v1"
        settings.VLLM_API_KEY = "EMPTY"

    # provider에 따라 기본 모델 결정
    if args.model is not None:
        model = args.model
    elif args.provider == "vllm":
        model = "qwen3:0.6b"
    elif args.provider == "local":
        model = "Qwen/Qwen2.5-1.5B-Instruct"
    else:
        model = settings.OPENAI_MODEL

    dataset_path = Path(args.dataset) if args.dataset else DATASET_PATH
    result_path = Path(args.output) if args.output else None

    if not dataset_path.exists():
        print(f"[오류] {dataset_path} 파일을 찾을 수 없습니다.")
        print("  먼저 generate_intent_rate.py를 실행하여 데이터셋을 생성하세요.")
        sys.exit(1)

    run_evaluation(
        dataset_path=dataset_path,
        result_path=result_path,
        model=model,
        provider=args.provider,
        num_samples=args.num_samples,
        batch_size=args.batch_size,
        parallel=args.parallel,
        difficulty=args.difficulty,
    )


if __name__ == "__main__":
    main()
