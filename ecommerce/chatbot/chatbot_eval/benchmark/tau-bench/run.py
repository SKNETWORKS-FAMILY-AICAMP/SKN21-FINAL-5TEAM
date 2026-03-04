"""
run.py

tau-bench 메인 실행 스크립트.

실행 예시:
    python run.py
    python run.py --tasks_file data/task_completion_rate_tasks.jsonl
    python run.py --tasks_file data/task_completion_rate_tasks.jsonl --task_ids GBD_TASK_001 GBD_TASK_011
    python run.py --tasks_file data/task_completion_rate_tasks.jsonl --debug
    python run.py --tasks_file data/task_completion_rate_tasks.jsonl --model gpt-4o --num_runs 4
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 경로 설정
BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))

from src.environment import TaskEnvironment
from src.user_simulator import UserSimulator, TASK_DONE_TOKEN, TASK_FAILED_TOKEN
from src.agent import ChatbotAgent
from src.evaluator import TaskEvaluator, format_eval_result
from src.metrics import save_metrics, print_metrics_summary

TASKS_PATH = BENCH_DIR / "data" / "tasks.jsonl"
OUTPUT_DIR = BENCH_DIR / "output"

# .env 로드
load_dotenv(BENCH_DIR.parents[4] / ".env")


def load_tasks(task_ids: list[str] | None = None, tasks_file: Path | None = None) -> list[dict]:
    """tasks.jsonl(또는 지정된 파일)에서 태스크를 로드합니다."""
    path = tasks_file if tasks_file else TASKS_PATH
    tasks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            task_id = str(task["task_id"])
            allowed: list[str] = task_ids or []  # type: ignore[assignment]
            if allowed and task_id not in allowed:
                continue
            tasks.append(task)
    return tasks


def run_single_episode(
    task: dict,
    agent: ChatbotAgent,
    simulator: UserSimulator,
    env: TaskEnvironment,
    max_turns: int,
    debug: bool = False,
) -> dict:
    """
    단일 태스크 에피소드를 실행합니다.

    Parameters:
        task: 태스크 정의
        agent: 챗봇 에이전트
        simulator: 유저 시뮬레이터
        env: 태스크 환경
        max_turns: 최대 대화 턴 수
        debug: 디버그 출력 여부

    Returns:
        에피소드 실행 결과 딕셔너리
    """
    agent.reset()
    simulator.reset(task)
    env.reset(task)

    trajectory = []
    turn: int = 0

    # 첫 번째 사용자 발화 생성
    user_msg = simulator.get_initial_message()
    if debug:
        print(f"  [User] {user_msg}")

    while turn < max_turns:
        # 챗봇 응답
        agent_reply = agent.respond(user_msg, env)
        if debug:
            print(f"  [Agent] {agent_reply[:200]}{'...' if len(agent_reply) > 200 else ''}")

        trajectory.append({"role": "assistant", "content": agent_reply})

        # 종료 조건 확인 (유저 신호 이전에 챗봇 응답으로도 확인)
        if simulator.is_done or simulator.is_failed:
            break

        # 유저 시뮬레이터 응답
        user_reply = simulator.respond(agent_reply)
        if debug:
            print(f"  [User] {user_reply}")

        trajectory.append({"role": "user", "content": user_reply})
        user_msg = user_reply
        turn += 1

        if simulator.is_done or simulator.is_failed:
            break

    return {
        "task_id": task["task_id"],
        "category": task.get("category", "unknown"),
        "trajectory": agent.get_trajectory(),
        "env_state": env.get_state_summary(),
        "user_done": simulator.is_done,
        "user_failed": simulator.is_failed,
        "total_turns": turn,
    }


def run_evaluation(args: argparse.Namespace) -> None:
    """tau-bench 평가 파이프라인을 실행합니다."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        sys.exit(1)

    print("🚀 τ-Bench 평가 시작...")
    print(f"   모델: {args.model}")
    print(f"   실행 횟수 (num_runs): {args.num_runs}")
    print(f"   최대 턴 수: {args.max_turns}")

    # 태스크 로드
    task_ids = args.task_ids if args.task_ids else None
    tasks_file = Path(args.tasks_file) if args.tasks_file else None
    tasks = load_tasks(task_ids, tasks_file)
    print(f"   태스크 파일: {tasks_file or TASKS_PATH}")
    print(f"   로드된 태스크: {len(tasks)}개")

    # 컴포넌트 초기화
    agent = ChatbotAgent(api_key=api_key, model=args.model, temperature=args.temperature)
    simulator = UserSimulator(
        api_key=api_key,
        model=args.user_model or args.model,
        temperature=0.7
    )
    evaluator = TaskEvaluator()

    # 출력 디렉토리 설정
    run_output_dir = OUTPUT_DIR / args.model / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_output_dir.mkdir(parents=True, exist_ok=True)

    all_eval_results: list[dict] = []
    raw_episodes: list[dict] = []

    # 평가 실행
    total_episodes = len(tasks) * args.num_runs
    episode_idx = 0

    for run_idx in range(args.num_runs):
        print(f"\n[Run {run_idx + 1}/{args.num_runs}]")
        for task in tasks:
            episode_idx += 1
            print(f"  ({episode_idx}/{total_episodes}) {task['task_id']} — {task.get('category', '')}...", end=" ")

            start_time = time.time()
            env = TaskEnvironment(task)

            try:
                episode = run_single_episode(
                    task=task,
                    agent=agent,
                    simulator=simulator,
                    env=env,
                    max_turns=args.max_turns,
                    debug=args.debug,
                )
            except Exception as e:
                print(f"❌ 오류: {e}")
                episode = {
                    "task_id": task["task_id"],
                    "category": task.get("category", "unknown"),
                    "trajectory": [],
                    "env_state": {},
                    "user_done": False,
                    "user_failed": True,
                    "total_turns": 0,
                    "error": str(e),
                }

            elapsed = time.time() - start_time

            # 평가
            eval_result = evaluator.evaluate(
                task=task,
                env=env,
                user_done=episode["user_done"],
                user_failed=episode["user_failed"],
                trajectory=episode["trajectory"],
            )
            eval_result["run_idx"] = run_idx
            eval_result["category"] = task.get("category", "unknown")
            eval_result["elapsed_sec"] = round(elapsed, 2)

            status_icon = "✅" if eval_result["success"] else "❌"
            print(f"{status_icon} ({elapsed:.1f}s, {eval_result['turn_count']}턴)")

            if args.debug:
                print(format_eval_result(eval_result))

            all_eval_results.append(eval_result)
            raw_episodes.append({**episode, "eval": eval_result})

    # 결과 저장
    results_path = run_output_dir / f"tau_bench.{args.model}.results.jsonl"
    with open(results_path, "w", encoding="utf-8") as f:
        for ep in raw_episodes:
            f.write(json.dumps(ep, ensure_ascii=False) + "\n")
    print(f"\n  ✓ 에피소드 결과 저장: {results_path}")

    # 지표 계산 및 저장
    metrics = save_metrics(
        eval_results=all_eval_results,
        model_name=args.model,
        output_dir=run_output_dir,
        k_values=[1, args.num_runs] if args.num_runs > 1 else [1],
    )

    print_metrics_summary(metrics)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="τ-Bench: 이커머스 챗봇 에이전트 평가 (tool-use + user simulator)"
    )
    parser.add_argument(
        "--model", type=str, default="gpt-4o-mini",
        help="평가할 챗봇 모델 (기본값: gpt-4o-mini)"
    )
    parser.add_argument(
        "--user_model", type=str, default=None,
        help="유저 시뮬레이터 모델 (기본값: --model과 동일)"
    )
    parser.add_argument(
        "--num_runs", type=int, default=1,
        help="태스크당 반복 실행 횟수 — Pass@k 계산에 사용 (기본값: 1)"
    )
    parser.add_argument(
        "--max_turns", type=int, default=10,
        help="에피소드당 최대 대화 턴 수 (기본값: 10)"
    )
    parser.add_argument(
        "--temperature", type=float, default=0.0,
        help="챗봇 에이전트 temperature (기본값: 0.0)"
    )
    parser.add_argument(
        "--task_ids", type=str, nargs="*", default=None,
        help="평가할 특정 태스크 ID 목록 (없으면 전체 실행)"
    )
    parser.add_argument(
        "--tasks_file", type=str, default="data/task_completion_rate_tasks.jsonl",
        help="태스크 JSONL 파일 경로 (기본값: data/task_completion_rate_tasks.jsonl)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="디버그 모드: 대화 내용 상세 출력"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_evaluation(args)
