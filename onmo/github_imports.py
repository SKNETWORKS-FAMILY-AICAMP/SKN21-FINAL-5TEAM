from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath

GITHUB_API_BASE = "https://api.github.com"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
class GitHubImportError(RuntimeError):
    pass


@dataclass(slots=True)
class GitHubRepoTarget:
    owner: str
    repo: str
    ref_name: str = ""
    source_subdir: str = ""


@dataclass(slots=True)
class GitHubRepoProbe:
    repo_url: str
    owner: str
    repo: str
    default_branch: str
    private: bool
    requires_auth: bool
    source_subdir: str = ""


def parse_github_repo_url(repo_url: str) -> GitHubRepoTarget:
    raw = str(repo_url or "").strip()
    if raw.startswith("git@github.com:"):
        path = raw.split("git@github.com:", 1)[1].strip().rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = [segment for segment in path.split("/") if segment]
        if len(parts) != 2:
            raise GitHubImportError("GitHub 저장소 URL 형식이 올바르지 않습니다.")
        owner, repo = parts
        return GitHubRepoTarget(owner=owner, repo=repo)

    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in {"github.com", "www.github.com"}:
        raise GitHubImportError("GitHub 저장소 URL 형식이 올바르지 않습니다.")
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [urllib.parse.unquote(segment).strip() for segment in path.split("/") if segment]
    if len(parts) < 2:
        raise GitHubImportError("GitHub 저장소 URL 형식이 올바르지 않습니다.")
    owner, repo = parts[0], parts[1]
    if not owner or not repo:
        raise GitHubImportError("GitHub 저장소 URL 형식이 올바르지 않습니다.")
    if len(parts) == 2:
        return GitHubRepoTarget(owner=owner, repo=repo)
    if len(parts) >= 4 and parts[2] == "tree":
        ref_name = parts[3].strip()
        if not ref_name:
            raise GitHubImportError("GitHub 저장소 branch 정보를 확인하지 못했습니다.")
        return GitHubRepoTarget(
            owner=owner,
            repo=repo,
            ref_name=ref_name,
            source_subdir=_normalize_source_subdir("/".join(parts[4:])),
        )
    raise GitHubImportError("GitHub 저장소 URL 형식이 올바르지 않습니다.")


def normalize_site_slug(repo: str) -> str:
    cleaned = str(repo or "").strip().lower().replace(" ", "-")
    slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in cleaned)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "github-site"


def build_github_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "repo",
            "state": state,
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{query}"


def probe_github_repository(repo_url: str, access_token: str | None = None) -> GitHubRepoProbe:
    target = parse_github_repo_url(repo_url)
    request = urllib.request.Request(
        f"{GITHUB_API_BASE}/repos/{target.owner}/{target.repo}",
        headers=_github_headers(access_token),
    )
    try:
        payload = _read_json_response(request)
    except urllib.error.HTTPError as exc:
        if access_token:
            raise GitHubImportError("GitHub 저장소에 접근할 수 없습니다.") from exc
        if int(exc.code) in {401, 403, 404}:
            return GitHubRepoProbe(
                repo_url=repo_url,
                owner=target.owner,
                repo=target.repo,
                default_branch=target.ref_name or "main",
                private=True,
                requires_auth=True,
                source_subdir=target.source_subdir,
            )
        raise GitHubImportError("GitHub 저장소 정보를 확인하지 못했습니다.") from exc
    except OSError as exc:
        raise GitHubImportError("GitHub 저장소 정보를 확인하지 못했습니다.") from exc

    return GitHubRepoProbe(
        repo_url=repo_url,
        owner=target.owner,
        repo=target.repo,
        default_branch=target.ref_name or str(payload.get("default_branch") or "main"),
        private=bool(payload.get("private")),
        requires_auth=False,
        source_subdir=target.source_subdir,
    )


def exchange_github_code_for_token(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> str:
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GITHUB_TOKEN_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ONMO GitHub Import",
        },
        method="POST",
    )
    try:
        payload = _read_json_response(request)
    except OSError as exc:
        raise GitHubImportError("GitHub 인증 토큰을 가져오지 못했습니다.") from exc

    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise GitHubImportError("GitHub 인증 토큰을 가져오지 못했습니다.")
    return token


def download_github_archive(
    *,
    owner: str,
    repo: str,
    branch: str,
    destination_root: Path,
    access_token: str | None = None,
) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/zipball/{urllib.parse.quote(branch)}",
        headers=_github_headers(access_token),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            archive_bytes = response.read()
    except urllib.error.HTTPError as exc:
        raise GitHubImportError("GitHub 저장소 소스를 가져오지 못했습니다.") from exc
    except OSError as exc:
        raise GitHubImportError("GitHub 저장소 소스를 가져오지 못했습니다.") from exc

    extract_root = destination_root / "extract"
    if extract_root.exists():
        for child in extract_root.iterdir():
            if child.is_dir():
                import shutil

                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        extract_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
            archive.extractall(extract_root)
    except zipfile.BadZipFile as exc:
        raise GitHubImportError("GitHub 저장소 압축 파일을 해제하지 못했습니다.") from exc

    directories = [path for path in extract_root.iterdir() if path.is_dir()]
    if len(directories) != 1:
        raise GitHubImportError("GitHub 저장소 압축 파일 구조를 해석하지 못했습니다.")
    return directories[0]


def resolve_github_source_root(extracted_root: Path, source_subdir: str) -> Path:
    root = extracted_root.resolve()
    normalized_subdir = _normalize_source_subdir(source_subdir)
    if not normalized_subdir:
        return root
    candidate = (root / Path(normalized_subdir)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GitHubImportError("GitHub 저장소 하위 경로 형식이 올바르지 않습니다.") from exc
    if not candidate.exists() or not candidate.is_dir():
        raise GitHubImportError("GitHub 저장소 하위 경로를 찾지 못했습니다.")
    return candidate


def iso_utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _github_headers(access_token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ONMO GitHub Import",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _read_json_response(request: urllib.request.Request) -> dict[str, object]:
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_source_subdir(source_subdir: str) -> str:
    raw = str(source_subdir or "").strip().strip("/")
    if not raw:
        return ""
    parts = [segment.strip() for segment in PurePosixPath(raw).parts if segment.strip()]
    if not parts or any(segment in {".", ".."} for segment in parts):
        raise GitHubImportError("GitHub 저장소 하위 경로 형식이 올바르지 않습니다.")
    return "/".join(parts)
