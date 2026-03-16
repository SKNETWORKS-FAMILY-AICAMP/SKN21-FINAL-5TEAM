from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from chatbot.src.onboarding.generator_eval import run_generator_eval
from chatbot.src.onboarding.role_runner import RoleRunner, build_llm_role_runner

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run golden evaluation for the onboarding Generator role."
    )
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--report-path")
    parser.add_argument("--use-llm-roles", action="store_true")
    parser.add_argument("--llm-provider", default="openai")
    parser.add_argument("--llm-model", default="gpt-4o-mini")
    return parser


def build_default_generator_role_runner() -> RoleRunner:
    return RoleRunner(
        responders={
            "Generator": lambda context: {
                "claim": "Prepared baseline overlay proposal",
                "evidence": context["evidence"],
                "confidence": 0.82,
                "risk": "medium",
                "next_action": "materialize baseline overlay artifacts",
                "blocking_issue": "none",
                "metadata": {
                    "proposed_files": [
                        "files/backend/chat_auth.py",
                        "files/backend/order_adapter_client.py",
                        "files/backend/product_adapter_client.py",
                    ],
                    "proposed_patches": [
                        "patches/frontend_widget_mount.patch",
                    ],
                },
            }
        }
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    role_runner = (
        build_llm_role_runner(provider=args.llm_provider, model=args.llm_model)
        if args.use_llm_roles
        else build_default_generator_role_runner()
    )
    summary = run_generator_eval(
        fixture_dir=args.fixture_dir,
        role_runner=role_runner,
        report_path=args.report_path,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
