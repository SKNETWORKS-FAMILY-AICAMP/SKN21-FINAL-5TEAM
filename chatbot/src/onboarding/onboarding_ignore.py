from __future__ import annotations

from pathlib import Path


DEFAULT_IGNORED_PARTS = {
    ".git",
    ".venv",
    ".onboarding_v2_runtime",
    "venv",
    "__pycache__",
    "site-packages",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
}


def runtime_copy_ignored_names(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name in DEFAULT_IGNORED_PARTS}


class OnboardingIgnoreMatcher:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.patterns = _load_patterns(self.root)

    def includes(self, path: Path) -> bool:
        relative = path.relative_to(self.root).as_posix()
        parts = set(path.relative_to(self.root).parts)
        if DEFAULT_IGNORED_PARTS & parts:
            return False
        for pattern in self.patterns:
            if relative == pattern or relative.startswith(f"{pattern}/"):
                return False
        return True


def _load_patterns(root: Path) -> list[str]:
    ignore_path = root / ".onboardingignore"
    if not ignore_path.exists():
        return []
    patterns: list[str] = []
    for line in ignore_path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        patterns.append(item.strip("/"))
    return patterns
