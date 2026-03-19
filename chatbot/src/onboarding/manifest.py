from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError


class OverlayManifestError(Exception):
    pass


class OverlayManifest(BaseModel):
    run_id: str
    site: str
    source_root: str
    created_at: str
    agent_version: str
    analysis: dict[str, Any]
    generated_files: list[str]
    patch_targets: list[str]
    frontend_artifacts: list[dict[str, Any]] = []
    docker: dict[str, Any]
    credentials: dict[str, str] = {}
    tests: dict[str, Any]
    status: Literal["generated", "applied", "approved", "rejected"]

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OverlayManifest":
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise OverlayManifestError(str(exc)) from exc
