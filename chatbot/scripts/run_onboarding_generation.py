from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.src.onboarding.orchestrator import run_onboarding_generation
from chatbot.src.onboarding.slack_bridge import SlackWebBridge

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run onboarding generation for a source site."
    )
    parser.add_argument("--site", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--generated-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-run-id")
    parser.add_argument("--agent-version", default="dev")
    parser.add_argument("--use-llm-roles", action="store_true")
    parser.add_argument("--llm-provider", default="openai")
    parser.add_argument("--llm-model", default="gpt-4o-mini")
    parser.add_argument("--print-report-paths", action="store_true")
    parser.add_argument("--slack-channel")
    parser.add_argument("--approval-store-root")
    parser.add_argument(
        "--approval",
        action="append",
        default=[],
        help="Approval decision in the form analysis=approve",
    )
    return parser


def build_slack_bridge_from_env(
    *, channel: str, web_client_factory=None
) -> SlackWebBridge | None:
    coordinator_token = os.getenv("SLACK_COORDINATOR_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    if not coordinator_token:
        return None

    web_factory = web_client_factory or _default_web_client_factory
    role_web_clients: dict[str, object] = {}
    role_env_names = {
        "Analyzer": "SLACK_ANALYZER_BOT_TOKEN",
        "Planner": "SLACK_PLANNER_BOT_TOKEN",
        "Generator": "SLACK_GENERATOR_BOT_TOKEN",
        "Validator": "SLACK_VALIDATOR_BOT_TOKEN",
        "Diagnostician": "SLACK_DIAGNOSTICIAN_BOT_TOKEN",
    }
    for role, env_name in role_env_names.items():
        token = os.getenv(env_name)
        if token:
            role_web_clients[role] = web_factory(token)
    return SlackWebBridge(
        channel=channel,
        web_client=web_factory(coordinator_token),
        role_web_clients=role_web_clients,
    )


def load_generation_env(*, project_root: str | Path = ROOT) -> None:
    load_dotenv(Path(project_root) / ".env", override=False)


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
    load_generation_env()
    effective_run_id = args.resume_run_id or args.run_id
    if not effective_run_id:
        parser.error("one of --run-id or --resume-run-id is required")
    approvals = parse_approvals(args.approval)
    slack_bridge = (
        build_slack_bridge_from_env(channel=args.slack_channel)
        if args.slack_channel
        else None
    )
    approval_store = (
        ApprovalStore(root=args.approval_store_root)
        if args.approval_store_root
        else None
    )

    result = run_onboarding_generation(
        site=args.site,
        source_root=args.source_root,
        generated_root=args.generated_root,
        runtime_root=args.runtime_root,
        run_id=effective_run_id,
        agent_version=args.agent_version,
        slack_bridge=slack_bridge,
        approval_decisions=approvals if approvals else None,
        approval_store=approval_store,
        use_llm_roles=args.use_llm_roles,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _default_web_client_factory(token: str):
    try:
        from slack_sdk.web import WebClient
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "slack_sdk is required to publish onboarding messages to Slack"
        ) from exc
    return WebClient(token=token)


if __name__ == "__main__":
    raise SystemExit(main())
