from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProbeExpectation(BaseModel):
    status: int = 200
    json_keys: list[str] = Field(default_factory=list)
    json_path_equals: dict[str, Any] = Field(default_factory=dict)
    json_path_not_empty: list[str] = Field(default_factory=list)
    header_contains: dict[str, str] = Field(default_factory=dict)
    body_contains: list[str] = Field(default_factory=list)
    json_type: str | None = None
    json_array_key: str | None = None
    json_array_min_length: int | None = None

    model_config = ConfigDict(extra="forbid")


class SmokeTestStep(BaseModel):
    id: str
    kind: str = "script"
    error: str | None = None
    strategy: str | None = None
    script: str | None = None
    method: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | str | None = None
    query: dict[str, str] | None = None
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 5
    required: bool = True
    category: str = "general"
    expects: ProbeExpectation = Field(default_factory=ProbeExpectation)
    exports: dict[str, str] = Field(default_factory=dict)
    uses: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _infer_defaults(self) -> "SmokeTestStep":
        if self.url and self.kind == "script":
            self.kind = "http"
        if self.script and self.category == "general":
            self.category = _infer_category_from_script(self.script)
        return self


class SmokeTestPlan(BaseModel):
    steps: list[SmokeTestStep]

    model_config = ConfigDict(extra="forbid")

    @field_validator("steps", mode="before")
    @classmethod
    def _normalize_steps(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[object] = []
        for item in value:
            if isinstance(item, str):
                normalized.append(
                    {
                        "id": Path(item).stem.replace("_", "-"),
                        "kind": "script",
                        "script": item,
                        "category": _infer_category_from_script(item),
                    }
                )
            else:
                normalized.append(item)
        return normalized


class SmokeRecoveryStepUpdate(BaseModel):
    step_id: str
    merge: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class SmokeRecoverySchemaOverride(BaseModel):
    step_id: str
    expects: ProbeExpectation | None = None
    exports: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class SmokeRecoveryPayload(BaseModel):
    classification: str
    should_retry: bool = False
    proposed_probe_updates: list[SmokeRecoveryStepUpdate] = Field(default_factory=list)
    proposed_schema_overrides: list[SmokeRecoverySchemaOverride] = Field(default_factory=list)
    repair_actions: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def _infer_category_from_script(script: str) -> str:
    stem = Path(script).stem.lower()
    if "chat_auth" in stem or "auth_token" in stem or stem == "me":
        return "auth"
    if "product" in stem:
        return "catalog"
    if "order" in stem:
        return "orders"
    return "general"
