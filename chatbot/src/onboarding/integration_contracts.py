from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_upper_token(value: str) -> str:
    return value.strip().upper().replace("-", "_").replace(" ", "_")


def _normalize_path_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = str(value).strip()
        if not candidate or candidate in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate)
    return normalized


class BackendContract(BaseModel):
    framework: str
    auth_style: str
    route_registration_points: list[str]
    auth_source_paths: list[str] = Field(default_factory=list)
    user_resolver_paths: list[str] = Field(default_factory=list)
    dependency_manifest_paths: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("framework", "auth_style", mode="before")
    @classmethod
    def _normalize_tokens(cls, value: str) -> str:
        return _normalize_token(str(value))

    @field_validator(
        "route_registration_points",
        "auth_source_paths",
        "user_resolver_paths",
        "dependency_manifest_paths",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return _normalize_path_list(list(value))


class FrontendContract(BaseModel):
    framework: str
    app_shell_path: str
    router_boundary_path: str | None = None
    auth_store_paths: list[str] = Field(default_factory=list)
    api_client_paths: list[str] = Field(default_factory=list)
    widget_mount_points: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("framework", mode="before")
    @classmethod
    def _normalize_framework(cls, value: str) -> str:
        return _normalize_token(str(value))

    @field_validator("app_shell_path", "router_boundary_path", mode="before")
    @classmethod
    def _normalize_optional_path(cls, value: Any) -> str | None:
        if value is None:
            return None
        candidate = str(value).strip()
        return candidate or None

    @field_validator("auth_store_paths", "api_client_paths", "widget_mount_points", mode="before")
    @classmethod
    def _normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return _normalize_path_list(list(value))


class ChatAuthContract(BaseModel):
    endpoint_path: str = "/api/chat/auth-token"
    method: str = "POST"
    authenticated_field: str = "authenticated"
    access_token_field: str = "access_token"

    model_config = ConfigDict(extra="forbid")

    @field_validator("endpoint_path", "authenticated_field", "access_token_field", mode="before")
    @classmethod
    def _normalize_pathish_fields(cls, value: Any) -> str:
        return str(value).strip()

    @field_validator("method", mode="before")
    @classmethod
    def _normalize_method(cls, value: Any) -> str:
        return _normalize_upper_token(str(value))


class ProductAdapterContract(BaseModel):
    enabled: bool = False
    client_path: str = "backend/product_adapter_client.py"
    tool_names: list[str] = Field(default_factory=list)
    api_base_paths: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("client_path", mode="before")
    @classmethod
    def _normalize_path(cls, value: Any) -> str:
        return str(value).strip()

    @field_validator("tool_names", "api_base_paths", mode="before")
    @classmethod
    def _normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return _normalize_path_list(list(value))


class OrderAdapterContract(BaseModel):
    enabled: bool = False
    client_path: str = "backend/order_adapter_client.py"
    tool_names: list[str] = Field(default_factory=list)
    api_base_paths: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("client_path", mode="before")
    @classmethod
    def _normalize_path(cls, value: Any) -> str:
        return str(value).strip()

    @field_validator("tool_names", "api_base_paths", mode="before")
    @classmethod
    def _normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return _normalize_path_list(list(value))


class SiteIntegrationContract(BaseModel):
    site: str
    backend: BackendContract
    frontend: FrontendContract
    chat_auth: ChatAuthContract = Field(default_factory=ChatAuthContract)
    product_adapter: ProductAdapterContract = Field(default_factory=ProductAdapterContract)
    order_adapter: OrderAdapterContract = Field(default_factory=OrderAdapterContract)

    model_config = ConfigDict(extra="forbid")

    @field_validator("site", mode="before")
    @classmethod
    def _normalize_site(cls, value: Any) -> str:
        return _normalize_token(str(value))
