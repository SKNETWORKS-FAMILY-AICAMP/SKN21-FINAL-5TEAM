from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import re
from urllib.parse import urlparse

from chatbot.src.onboarding_v2.models.analysis import RagSources
from chatbot.src.onboarding_v2.models.planning import RagCorpusPlan, RetrievalIndexPlan


def _normalize_site_slug(site: str) -> str:
    cleaned = str(site or "").strip().lower().replace(" ", "_")
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in cleaned)


def build_indexing_plan(*, site: str, run_id: str, rag_sources: RagSources) -> RetrievalIndexPlan:
    site_slug = _normalize_site_slug(site)
    corpora: list[RagCorpusPlan] = []
    specs = {
        "faq": ("qa_level", rag_sources.faq, ["배송은 얼마나 걸리나요?"], "faq_source_scan"),
        "policy": ("heading_sections", rag_sources.policy, ["환불 규정"], "policy_source_scan"),
        "discovery_image": ("entity_level", rag_sources.discovery_image, ["검은색 자켓"], "public_url_fetch"),
    }
    for corpus, (chunking_strategy, records, smoke_queries, loader_strategy) in specs.items():
        if not records:
            continue
        resolved_loader_strategy = _resolve_loader_strategy(
            corpus=corpus,
            records=records,
            default_loader=loader_strategy,
        )
        corpora.append(
            RagCorpusPlan(
                corpus=corpus,
                enabled=True,
                chunking_strategy=chunking_strategy,
                collection_alias=f"site_{site_slug}__{corpus}",
                build_collection=f"site_{site_slug}__{corpus}__run_{run_id}",
                sources=[record.path for record in records],
                smoke_queries=list(smoke_queries),
                minimum_expected_documents=1,
                loader_strategy=resolved_loader_strategy,
            )
        )
    return RetrievalIndexPlan(site_id=site, site_slug=site_slug, corpora=corpora)


def _resolve_loader_strategy(
    *,
    corpus: str,
    records: list[Any],
    default_loader: str,
) -> str:
    if corpus != "discovery_image":
        return default_loader
    discovered: list[str] = []
    for record in records:
        details = getattr(record, "details", {}) or {}
        for candidate in list(details.get("loader_candidates") or []):
            value = str(candidate).strip()
            if value:
                discovered.append(value)
        explicit = str(details.get("loader_strategy") or "").strip()
        if explicit:
            discovered.append(explicit)
    for candidate in ("public_url_fetch", "signed_url_resolver", "bucket_list_and_fetch"):
        if candidate in discovered:
            return candidate
    return default_loader


def chunk_faq_source(source_path: str | Path) -> list[dict[str, Any]]:
    path = Path(source_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    chunks: list[dict[str, Any]] = []
    for index, entry in enumerate(payload):
        question = str(entry.get("question") or "").strip()
        answer = str(entry.get("answer") or "").strip()
        if not question or not answer:
            continue
        chunks.append(
            {
                "chunk_id": f"faq-{index:04d}",
                "question": question,
                "answer": answer,
                "text": f"질문: {question}\n답변: {answer}",
            }
        )
    return chunks


def chunk_policy_source(source_path: str | Path) -> list[dict[str, Any]]:
    path = Path(source_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    chunks: list[dict[str, Any]] = []
    current_heading = ""
    current_lines: list[str] = []

    def flush() -> None:
        if not current_heading and not current_lines:
            return
        text = "\n".join(line for line in current_lines if line.strip()).strip()
        if not text:
            return
        chunks.append(
            {
                "chunk_id": f"policy-{len(chunks):04d}",
                "heading": current_heading or "document",
                "text": text,
            }
        )

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("#"):
            flush()
            current_heading = line.lstrip("#").strip()
            current_lines = []
            continue
        current_lines.append(raw_line)
    flush()
    return chunks


def execute_indexing_plan(
    *,
    plan: RetrievalIndexPlan,
    root: str | Path,
    worker: Any | None = None,
) -> dict[str, Any]:
    base_root = Path(root)
    worker_fn = worker or _default_worker
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(3, len(plan.corpora)))) as executor:
        future_map = {
            executor.submit(worker_fn, corpus_plan=corpus, root=base_root): corpus.corpus
            for corpus in plan.corpora
        }
        for future in as_completed(future_map):
            corpus = future_map[future]
            try:
                results[corpus] = future.result()
            except Exception as exc:
                results[corpus] = {
                    "status": "failed",
                    "enabled": False,
                    "error": str(exc),
                }
    return {
        "site_id": plan.site_id,
        "site_slug": plan.site_slug,
        "corpora": results,
    }


def _default_worker(*, corpus_plan: RagCorpusPlan, root: Path) -> dict[str, Any]:
    available = [source for source in corpus_plan.sources if (root / source).exists()]
    if not available:
        return {
            "status": "failed",
            "enabled": False,
            "documents_indexed": 0,
            "reason": "no_accessible_sources",
        }
    if corpus_plan.corpus == "discovery_image":
        discovered_urls = _discover_public_image_urls(root=root, source_paths=available)
        indexed = len(discovered_urls)
        status = "completed" if indexed >= 1 else "failed"
        failure_warning = [] if indexed else ["no_reachable_public_image_urls"]
        return {
            "status": status,
            "enabled": indexed >= 1,
            "documents_indexed": indexed,
            "collection_alias": corpus_plan.collection_alias,
            "build_collection": corpus_plan.build_collection,
            "loader_strategy": corpus_plan.loader_strategy,
            "discovered_urls": len(discovered_urls),
            "warning_codes": failure_warning,
            "smoke_passed": indexed >= max(1, corpus_plan.minimum_expected_documents),
        }
    return {
        "status": "completed",
        "enabled": True,
        "documents_indexed": len(available),
        "collection_alias": corpus_plan.collection_alias,
        "build_collection": corpus_plan.build_collection,
        "loader_strategy": corpus_plan.loader_strategy,
    }


def _discover_public_image_urls(*, root: Path, source_paths: list[str]) -> list[str]:
    urls: list[str] = []
    pattern = re.compile(r"https?://[^\s\"')]+", re.IGNORECASE)
    for source_path in source_paths:
        path = root / source_path
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.findall(text):
            parsed = urlparse(match)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                urls.append(match.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped
