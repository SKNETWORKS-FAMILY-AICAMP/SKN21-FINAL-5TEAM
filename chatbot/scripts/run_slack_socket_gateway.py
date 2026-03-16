from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from chatbot.src.onboarding.approval_store import ApprovalStore
from chatbot.src.onboarding.slack_socket_gateway import register_socket_mode_handler
from chatbot.src.onboarding.slack_bridge import SlackWebBridge

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Slack Socket Mode gateway for onboarding approvals."
    )
    parser.add_argument("--channel", required=True)
    parser.add_argument("--approval-store-root", required=True)
    parser.add_argument("--site")
    parser.add_argument("--source-root")
    parser.add_argument("--generated-root")
    parser.add_argument("--runtime-root")
    parser.add_argument("--agent-version", default="dev")
    return parser


def load_gateway_env(*, project_root: str | Path = ROOT) -> None:
    load_dotenv(Path(project_root) / ".env", override=False)


def run_gateway(
    *,
    channel: str,
    approval_store_root: str | Path,
    bot_token: str,
    app_token: str,
    resume_run=None,
    socket_client_factory=None,
    web_client_factory=None,
    connect: bool = True,
    run_forever: bool = True,
    sleep_fn=time.sleep,
    logger=None,
) -> int:
    socket_factory = socket_client_factory or _default_socket_client_factory
    web_factory = web_client_factory or _default_web_client_factory
    active_logger = logger or _default_logger()

    store = ApprovalStore(root=approval_store_root)
    web_client = web_factory(bot_token)
    bridge = SlackWebBridge(channel=channel, web_client=web_client)
    socket_client = socket_factory(app_token=app_token, web_client=web_client)
    active_logger.info("gateway started for channel=%s", channel)
    register_socket_mode_handler(
        client=socket_client,
        store=store,
        bridge=bridge,
        resume_run=resume_run,
        ack=lambda envelope_id: None,
    )
    if connect and hasattr(socket_client, "connect"):
        active_logger.info("gateway connecting")
        socket_client.connect()
        active_logger.info("gateway connected")
    if run_forever:
        try:
            while True:
                sleep_fn(1.0)
        except KeyboardInterrupt:
            active_logger.info("gateway stopped")
            return 0
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    load_gateway_env()
    bot_token = os.getenv("SLACK_COORDINATOR_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        raise SystemExit(
            "SLACK_COORDINATOR_BOT_TOKEN (or SLACK_BOT_TOKEN) and SLACK_APP_TOKEN are required"
        )

    return run_gateway(
        channel=args.channel,
        approval_store_root=args.approval_store_root,
        bot_token=bot_token,
        app_token=app_token,
        resume_run=_build_resume_runner(
            channel=args.channel,
            approval_store_root=args.approval_store_root,
            site=args.site,
            source_root=args.source_root,
            generated_root=args.generated_root,
            runtime_root=args.runtime_root,
            agent_version=args.agent_version,
            logger=_default_logger(),
        ),
    )


def _default_web_client_factory(token: str):
    try:
        from slack_sdk.web import WebClient
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("slack_sdk is required to run the socket gateway") from exc
    return WebClient(token=token)


def _default_socket_client_factory(*, app_token: str, web_client):
    try:
        from slack_sdk.socket_mode import SocketModeClient
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("slack_sdk is required to run the socket gateway") from exc
    return SocketModeClient(app_token=app_token, web_client=web_client)


def _default_logger():
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def _build_resume_runner(
    *,
    channel: str,
    approval_store_root: str | Path,
    site: str | None,
    source_root: str | None,
    generated_root: str | None,
    runtime_root: str | None,
    agent_version: str,
    logger,
):
    if not all([site, source_root, generated_root, runtime_root]):
        return None

    def _resume(run_id: str, approval_type: str) -> None:
        logger.info(
            "gateway auto-resuming run=%s after %s approval", run_id, approval_type
        )
        result = subprocess.run(
            [
                sys.executable,
                "chatbot/scripts/run_onboarding_generation.py",
                "--site",
                str(site),
                "--source-root",
                str(source_root),
                "--generated-root",
                str(generated_root),
                "--runtime-root",
                str(runtime_root),
                "--resume-run-id",
                run_id,
                "--agent-version",
                agent_version,
                "--approval-store-root",
                str(approval_store_root),
                "--slack-channel",
                channel,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.exception(
                "gateway auto-resume failed for run=%s: %s",
                run_id,
                (result.stderr or result.stdout or "").strip(),
            )

    return _resume


if __name__ == "__main__":
    raise SystemExit(main())
