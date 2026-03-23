from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


OperationName = Literal["replace_text", "insert_after", "insert_before", "append_text"]


class EditOperation(BaseModel):
    path: str
    operation: OperationName
    old: str | None = None
    new: str | None = None
    anchor: str | None = None
    content: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("path", "old", "new", "anchor", "content", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)


class SupportingArtifactBundle(BaseModel):
    bundle_id: str
    path: str
    content: str
    reason: str

    model_config = ConfigDict(extra="forbid")


class BackendWiringBundle(BaseModel):
    bundle_id: str
    strategy: str
    target_paths: list[str]
    operations: list[EditOperation] = Field(default_factory=list)
    supporting_files: list[SupportingArtifactBundle] = Field(default_factory=list)
    handler_reference: str | None = None

    model_config = ConfigDict(extra="forbid")


class FrontendMountBundle(BaseModel):
    bundle_id: str
    strategy: str
    target_path: str
    operations: list[EditOperation] = Field(default_factory=list)
    host_contract_marker: str = "__ORDER_CS_WIDGET_HOST_CONTRACT__"

    model_config = ConfigDict(extra="forbid")


class FrontendApiBundle(BaseModel):
    bundle_id: str
    strategy: str
    target_path: str
    operations: list[EditOperation] = Field(default_factory=list)
    auth_bootstrap_path: str = "/api/chat/auth-token"

    model_config = ConfigDict(extra="forbid")


class ChatbotBridgeBundle(BaseModel):
    bundle_id: str
    strategy: str = "chatbot_generated_adapter"
    target_paths: list[str] = Field(default_factory=list)
    operations: list[EditOperation] = Field(default_factory=list)
    supporting_files: list[SupportingArtifactBundle] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class HostEditProgram(BaseModel):
    backend_wiring_bundles: list[BackendWiringBundle] = Field(default_factory=list)
    frontend_mount_bundles: list[FrontendMountBundle] = Field(default_factory=list)
    frontend_api_bundles: list[FrontendApiBundle] = Field(default_factory=list)
    supporting_artifact_bundles: list[SupportingArtifactBundle] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ChatbotEditProgram(BaseModel):
    bridge_bundles: list[ChatbotBridgeBundle] = Field(default_factory=list)
    supporting_artifact_bundles: list[SupportingArtifactBundle] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class EditProgram(BaseModel):
    host_program: HostEditProgram = Field(default_factory=HostEditProgram)
    chatbot_program: ChatbotEditProgram = Field(default_factory=ChatbotEditProgram)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @property
    def backend_wiring_bundles(self) -> list[BackendWiringBundle]:
        return self.host_program.backend_wiring_bundles

    @property
    def frontend_mount_bundles(self) -> list[FrontendMountBundle]:
        return self.host_program.frontend_mount_bundles

    @property
    def frontend_api_bundles(self) -> list[FrontendApiBundle]:
        return self.host_program.frontend_api_bundles

    @property
    def supporting_artifact_bundles(self) -> list[SupportingArtifactBundle]:
        return self.host_program.supporting_artifact_bundles

