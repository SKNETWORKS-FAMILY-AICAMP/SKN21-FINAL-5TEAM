from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

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
        "discovery_image": ("entity_level", rag_sources.discovery_image, ["검은색 자켓"], "discovery_image_scan"),
    }
    for corpus, (chunking_strategy, records, smoke_queries, loader_strategy) in specs.items():
        if not records:
            continue
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
                loader_strategy=str(records[0].details.get("loader_strategy") or loader_strategy),
            )
        )
    return RetrievalIndexPlan(site_id=site, site_slug=site_slug, corpora=corpora)


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
    return {
        "status": "completed",
        "enabled": True,
        "documents_indexed": len(available),
        "collection_alias": corpus_plan.collection_alias,
        "build_collection": corpus_plan.build_collection,
        "loader_strategy": corpus_plan.loader_strategy,
    }
