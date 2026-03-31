from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrandProfile:
    site_id: str
    display_name: str

    @property
    def store_label(self) -> str:
        return f"{self.display_name} 쇼핑몰"

    @property
    def assistant_title(self) -> str:
        return f"{self.display_name} AI 고객상담사"

    @property
    def initial_greeting(self) -> str:
        return f"안녕하세요. {self.display_name} 챗봇입니다."


_BRAND_PROFILES: dict[str, BrandProfile] = {
    "site-a": BrandProfile(site_id="site-a", display_name="food"),
    "site-b": BrandProfile(site_id="site-b", display_name="bilyeo"),
    "site-c": BrandProfile(site_id="site-c", display_name="moyeo"),
}

_DEFAULT_BRAND_PROFILE = _BRAND_PROFILES["site-c"]
_BRAND_PROFILE_ALIASES: dict[str, BrandProfile] = {
    profile.display_name.strip().lower(): profile
    for profile in _BRAND_PROFILES.values()
}


def _derive_display_name(site_id: str) -> str:
    normalized = str(site_id or "").strip().lower()
    if not normalized:
        return _DEFAULT_BRAND_PROFILE.display_name
    return normalized.replace("_", " ").replace("-", " ")


def resolve_brand_profile(site_id: str | None) -> BrandProfile:
    normalized = str(site_id or "").strip().lower()
    if not normalized:
        return _DEFAULT_BRAND_PROFILE
    direct_match = _BRAND_PROFILES.get(normalized)
    if direct_match is not None:
        return direct_match

    alias_match = _BRAND_PROFILE_ALIASES.get(normalized)
    if alias_match is not None:
        return BrandProfile(site_id=normalized, display_name=alias_match.display_name)

    return BrandProfile(site_id=normalized, display_name=_derive_display_name(normalized))


def store_label_for_site(site_id: str | None) -> str:
    return resolve_brand_profile(site_id).store_label
