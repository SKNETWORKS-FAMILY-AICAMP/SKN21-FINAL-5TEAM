from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatbot.src.onboarding.orchestrator import run_onboarding_generation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run onboarding generation for a source site."
    )
    parser.add_argument("--site", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--generated-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--agent-version", default="dev")
    parser.add_argument("--use-llm-roles", action="store_true")
    parser.add_argument("--llm-provider", default="openai")
    parser.add_argument("--llm-model", default="gpt-4o-mini")
    parser.add_argument("--print-report-paths", action="store_true")
    parser.add_argument(
        "--approval",
        action="append",
        default=[],
        help="Approval decision in the form analysis=approve",
    )
    return parser


def parse_approvals(items: list[str]) -> dict[str, str]:
    approvals: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid approval format: {item}")
        key, value = item.split("=", 1)
        approvals[key.strip()] = value.strip()
    return approvals


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    approvals = parse_approvals(args.approval)

    result = run_onboarding_generation(
        site=args.site,
        source_root=args.source_root,
        generated_root=args.generated_root,
        runtime_root=args.runtime_root,
        run_id=args.run_id,
        agent_version=args.agent_version,
        approval_decisions=approvals if approvals else None,
        use_llm_roles=args.use_llm_roles,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
