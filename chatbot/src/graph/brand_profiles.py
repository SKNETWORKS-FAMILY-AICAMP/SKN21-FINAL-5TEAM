from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrandProfile:
    site_id: str
    display_name: str

    @property
    def store_label(self) -> str:
        return f"{self.display_name} 쇼핑몰"


_BRAND_PROFILES: dict[str, BrandProfile] = {
    "site-a": BrandProfile(site_id="site-a", display_name="food"),
    "site-b": BrandProfile(site_id="site-b", display_name="bilyeo"),
    "site-c": BrandProfile(site_id="site-c", display_name="moyeo"),
}

_DEFAULT_BRAND_PROFILE = _BRAND_PROFILES["site-c"]


def resolve_brand_profile(site_id: str | None) -> BrandProfile:
    normalized = str(site_id or "").strip().lower()
    if not normalized:
        return _DEFAULT_BRAND_PROFILE
    return _BRAND_PROFILES.get(normalized, _DEFAULT_BRAND_PROFILE)


def store_label_for_site(site_id: str | None) -> str:
    return resolve_brand_profile(site_id).store_label
