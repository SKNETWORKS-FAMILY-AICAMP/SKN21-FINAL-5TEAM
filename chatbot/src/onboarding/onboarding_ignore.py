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

_CHATBOT_RUNTIME_ROOT_IGNORED_NAMES = {
    "chatbot_eval",
    "tests",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    ".cache",
}
_CHATBOT_SRC_IGNORED_NAMES = {
    "chatbot_logs",
}


def _resolve_chatbot_runtime_root(current_dir: str | Path) -> Path | None:
    current = Path(current_dir)
    for candidate in (current, *current.parents):
        if (
            (candidate / "server_fastapi.py").is_file()
            and (candidate / "src").is_dir()
            and (candidate / "frontend").is_dir()
        ):
            return candidate
    return None


def _preserve_runtime_directory(current_dir: str | Path, candidate_name: str) -> bool:
    path = Path(current_dir)
    if candidate_name != "dist":
        return False
    return tuple(path.parts[-2:]) == ("frontend", "shared_widget")


def _context_specific_runtime_ignored_names(
    current_dir: str | Path,
    names: list[str],
) -> set[str]:
    chatbot_root = _resolve_chatbot_runtime_root(current_dir)
    if chatbot_root is None:
        return set()
    current = Path(current_dir)
    try:
        relative_parts = current.relative_to(chatbot_root).parts
    except ValueError:
        return set()
    available_names = set(names)
    if not relative_parts:
        return _CHATBOT_RUNTIME_ROOT_IGNORED_NAMES & available_names
    if relative_parts == ("src",):
        return _CHATBOT_SRC_IGNORED_NAMES & available_names
    return set()


def runtime_copy_ignored_names(current_dir: str, names: list[str]) -> set[str]:
    ignored = {
        name
        for name in names
        if name in DEFAULT_IGNORED_PARTS
        and not _preserve_runtime_directory(current_dir, name)
    }
    ignored.update(_context_specific_runtime_ignored_names(current_dir, names))
    return ignored


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
