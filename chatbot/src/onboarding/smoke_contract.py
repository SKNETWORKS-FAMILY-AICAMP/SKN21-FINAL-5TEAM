from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SmokeTestStep(BaseModel):
    id: str
    script: str
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 5
    required: bool = True
    category: str = "general"

    model_config = ConfigDict(extra="forbid")


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
                        "script": item,
                    }
                )
            else:
                normalized.append(item)
        return normalized
