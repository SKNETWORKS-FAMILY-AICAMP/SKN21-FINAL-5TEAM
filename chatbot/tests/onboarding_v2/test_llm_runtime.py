import json
import os
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")

from chatbot.src.onboarding_v2.llm_runtime import invoke_structured_stage
from chatbot.src.onboarding_v2.stage_tools import StageToolRuntime
from chatbot.src.onboarding_v2.storage import DebugStore, LlmUsageStore


class _RepairEnvelope(BaseModel):
    failure_signature: str
    diagnosis: str
    rewind_to: str
    preserve_artifacts: list[str]
    required_rechecks: list[str]
    additional_discovery: list[dict[str, str]]
    artifact_overrides: dict[str, object]
    stop: bool
    stop_reason: str | None = None

    model_config = ConfigDict(extra="forbid")


class _ToolAwareLlm:
    def __init__(self) -> None:
        self.invocations: list[list[object]] = []

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        self.bind_kwargs = dict(kwargs)
        return self

    def invoke(self, messages):
        self.invocations.append(list(messages))
        if not any(isinstance(message, ToolMessage) for message in messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-list",
                        "name": "list_repair_paths",
                        "args": {},
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            )
        return AIMessage(
            content=json.dumps(
                {
                    "failure_signature": "smoke_failed",
                    "diagnosis": "tool-assisted diagnosis",
                    "rewind_to": "validation",
                    "preserve_artifacts": ["analysis"],
                    "required_rechecks": [],
                    "additional_discovery": [],
                    "artifact_overrides": {},
                    "stop": False,
                    "stop_reason": None,
                }
            ),
            usage_metadata={"input_tokens": 7, "output_tokens": 5, "total_tokens": 12},
        )


class _NoBindToolsLlm:
    def invoke(self, messages):
        del messages
        return AIMessage(
            content=json.dumps(
                {
                    "failure_signature": "smoke_failed",
                    "diagnosis": "plain invoke path",
                    "rewind_to": "validation",
                    "preserve_artifacts": [],
                    "required_rechecks": [],
                    "additional_discovery": [],
                    "artifact_overrides": {},
                    "stop": False,
                    "stop_reason": None,
                }
            )
        )


class _EndlessToolLlm:
    def bind_tools(self, tools, **kwargs):
        del tools, kwargs
        return self

    def invoke(self, messages):
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-loop",
                    "name": "list_repair_paths",
                    "args": {},
                }
            ],
        )


def _tool_runtime() -> StageToolRuntime:
    return StageToolRuntime(
        stage="repair",
        root=ROOT,
        allowed_paths=("backend/app.py",),
        tools=[
            StructuredTool.from_function(
                name="list_repair_paths",
                description="List allowed repair paths.",
                func=lambda: {"paths": ["backend/app.py"]},
            )
        ],
    )


def test_invoke_structured_stage_executes_tool_calls_until_structured_response(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-v2"
    debug_store = DebugStore(run_root)
    usage_store = LlmUsageStore(run_root)
    llm = _ToolAwareLlm()

    result = invoke_structured_stage(
        stage="repair",
        phase="diagnosis",
        provider="openai",
        model="gpt-5-mini",
        system_prompt="return JSON",
        payload={"failure_signature": "smoke_failed"},
        response_model=_RepairEnvelope,
        fallback_payload={
            "failure_signature": "fallback",
            "diagnosis": "fallback",
            "rewind_to": "validation",
            "preserve_artifacts": [],
            "required_rechecks": [],
            "additional_discovery": [],
            "artifact_overrides": {},
            "stop": True,
            "stop_reason": "fallback",
        },
        debug_store=debug_store,
        usage_store=usage_store,
        llm_builder=lambda provider, model, temperature: llm,
        tool_runtime=_tool_runtime(),
    )

    assert result.diagnosis == "tool-assisted diagnosis"
    debug_payload = json.loads(
        (run_root / "debug" / "llm" / "repair" / "attempt-0001-diagnosis.json").read_text(encoding="utf-8")
    )
    assert debug_payload["response"]["tool_trace"][0]["tool_name"] == "list_repair_paths"
    usage_payload = json.loads((run_root / "debug" / "llm-usage-summary.json").read_text(encoding="utf-8"))
    assert usage_payload["calls"][0]["details"]["tool_call_count"] == 1
    assert usage_payload["calls"][0]["details"]["tool_names"] == ["list_repair_paths"]


def test_invoke_structured_stage_uses_plain_invoke_when_bind_tools_is_unsupported():
    result = invoke_structured_stage(
        stage="repair",
        phase="diagnosis",
        provider="openai",
        model="gpt-5-mini",
        system_prompt="return JSON",
        payload={"failure_signature": "smoke_failed"},
        response_model=_RepairEnvelope,
        fallback_payload={
            "failure_signature": "fallback",
            "diagnosis": "fallback",
            "rewind_to": "validation",
            "preserve_artifacts": [],
            "required_rechecks": [],
            "additional_discovery": [],
            "artifact_overrides": {},
            "stop": True,
            "stop_reason": "fallback",
        },
        llm_builder=lambda provider, model, temperature: _NoBindToolsLlm(),
        tool_runtime=_tool_runtime(),
    )

    assert result.diagnosis == "plain invoke path"


def test_invoke_structured_stage_falls_back_when_tool_round_limit_is_exceeded():
    result = invoke_structured_stage(
        stage="repair",
        phase="diagnosis",
        provider="openai",
        model="gpt-5-mini",
        system_prompt="return JSON",
        payload={"failure_signature": "smoke_failed"},
        response_model=_RepairEnvelope,
        fallback_payload={
            "failure_signature": "fallback",
            "diagnosis": "fallback",
            "rewind_to": "validation",
            "preserve_artifacts": [],
            "required_rechecks": [],
            "additional_discovery": [],
            "artifact_overrides": {},
            "stop": True,
            "stop_reason": "fallback",
        },
        llm_builder=lambda provider, model, temperature: _EndlessToolLlm(),
        tool_runtime=_tool_runtime(),
        max_tool_rounds=1,
    )

    assert result.failure_signature == "fallback"
    assert result.stop is True
