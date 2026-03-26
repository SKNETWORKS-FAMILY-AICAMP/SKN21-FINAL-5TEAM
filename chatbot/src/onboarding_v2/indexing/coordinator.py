from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse
from uuid import NAMESPACE_URL, uuid5

import httpx
from PIL import Image
from qdrant_client.http import models

from chatbot.src.infrastructure.site_retrieval import (
    ensure_build_collection,
    swap_alias,
    upsert_points,
)
from chatbot.src.onboarding_v2.models.analysis import AnalysisSnapshot, RagSources
from chatbot.src.onboarding_v2.models.planning import IntegrationPlan, RagCorpusPlan, RetrievalIndexPlan
from chatbot.src.onboarding_v2.validation.backend_runtime import (
    build_backend_subprocess_env,
    build_backend_runtime_plan,
    launch_backend_runtime,
    prepare_backend_runtime,
    stop_backend_runtime,
)
from chatbot.src.data_preprocessing.bge_m3_embedding import embed_texts


@dataclass(slots=True)
class HostExportContext:
    host_runtime_workspace: Path | None = None
    snapshot: AnalysisSnapshot | None = None
    integration_plan: IntegrationPlan | None = None
    export_ready: Event = field(default_factory=Event)
    host_failed: Event = field(default_factory=Event)


@dataclass(slots=True)
class _IndexingDeps:
    qdrant_client: object | None = None
    dense_embedder: Callable[[list[str]], list[list[float]]] = embed_texts
    sparse_embedder: Callable[[list[str]], list[models.SparseVector]] | None = None
    image_embedder: Callable[[list[bytes]], list[list[float]]] | None = None
    image_fetcher: Callable[[str], bytes] | None = None
    row_fetcher: Callable[..., list[dict[str, Any]]] | None = None


def _normalize_site_slug(site: str) -> str:
    cleaned = str(site or "").strip().lower().replace(" ", "_")
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in cleaned)


def build_indexing_plan(
    *,
    site: str,
    run_id: str,
    rag_sources: RagSources,
    product_search_endpoint: str = "",
) -> RetrievalIndexPlan:
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
            _build_rag_corpus_plan(
                corpus=corpus,
                chunking_strategy=chunking_strategy,
                collection_alias=f"site_{site_slug}__{corpus}",
                build_collection=f"site_{site_slug}__{corpus}__run_{run_id}",
                records=records,
                smoke_queries=list(smoke_queries),
                loader_strategy=resolved_loader_strategy,
                product_search_endpoint=product_search_endpoint,
            )
        )
    return RetrievalIndexPlan(site_id=site, site_slug=site_slug, corpora=corpora)


def _resolve_faq_row_source(
    *,
    records: list[Any],
) -> tuple[str, str | None, str | None]:
    for record in records:
        details = getattr(record, "details", {}) or {}
        strategy = str(details.get("row_source_strategy") or "").strip()
        module_name = str(details.get("row_source_module") or "").strip()
        callable_name = str(details.get("row_source_callable") or "").strip()
        if strategy == "host_python_fetch":
            return (
                "host_python_fetch",
                module_name or "models.faq",
                callable_name or "get_all_faq",
            )
        normalized_path = str(getattr(record, "path", "") or "").replace("\\", "/").lower()
        if normalized_path.endswith("backend/models/faq.py"):
            return ("host_python_fetch", "models.faq", "get_all_faq")
        if normalized_path.endswith((".json", ".csv", ".md", ".txt")):
            return ("static_source_scan", None, None)
    return ("static_source_scan", None, None)


def _build_rag_corpus_plan(
    *,
    corpus: str,
    chunking_strategy: str,
    collection_alias: str,
    build_collection: str,
    records: list[Any],
    smoke_queries: list[str],
    loader_strategy: str,
    product_search_endpoint: str,
) -> RagCorpusPlan:
    faq_row_source_strategy = None
    faq_row_source_module = None
    faq_row_source_callable = None
    if corpus == "faq":
        faq_row_source_strategy, faq_row_source_module, faq_row_source_callable = _resolve_faq_row_source(
            records=records,
        )
    if corpus != "discovery_image":
        return RagCorpusPlan(
            corpus=corpus,
            enabled=True,
            chunking_strategy=chunking_strategy,
            collection_alias=collection_alias,
            build_collection=build_collection,
            sources=[record.path for record in records],
            smoke_queries=smoke_queries,
            minimum_expected_documents=1,
            loader_strategy=loader_strategy,
            row_source_strategy=faq_row_source_strategy,
            row_source_module=faq_row_source_module,
            row_source_callable=faq_row_source_callable,
        )

    image_field = next(
        (
            str((getattr(record, "details", {}) or {}).get("image_field") or "").strip()
            for record in records
            if str((getattr(record, "details", {}) or {}).get("image_field") or "").strip()
        ),
        "image_url",
    )
    return RagCorpusPlan(
        corpus=corpus,
        enabled=True,
        chunking_strategy=chunking_strategy,
        collection_alias=collection_alias,
        build_collection=build_collection,
        sources=[record.path for record in records],
        smoke_queries=smoke_queries,
        minimum_expected_documents=1,
        loader_strategy=loader_strategy,
        row_source_strategy="host_api_fetch",
        row_source_endpoint=product_search_endpoint,
        row_id_field="product_id",
        row_image_url_field=image_field or "image_url",
        pagination_strategy={
            "type": "page_number",
            "page_param": "page",
            "page_size_param": "page_size",
            "page_size": 100,
            "stop_on": "empty_or_repeated_ids",
        },
    )


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
    if not isinstance(payload, list):
        return []
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
                "main_category": str(entry.get("main_category") or "").strip(),
                "sub_category": str(entry.get("sub_category") or "").strip(),
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
    cancel_event: Event | None = None,
    host_context: HostExportContext | None = None,
    qdrant_client: object | None = None,
    dense_embedder: Callable[[list[str]], list[list[float]]] = embed_texts,
    sparse_embedder: Callable[[list[str]], list[models.SparseVector]] | None = None,
    image_embedder: Callable[[list[bytes]], list[list[float]]] | None = None,
    image_fetcher: Callable[[str], bytes] | None = None,
    row_fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    worker: Any | None = None,
) -> dict[str, Any]:
    base_root = Path(root)
    worker_fn = worker or _default_worker
    deps = _IndexingDeps(
        qdrant_client=qdrant_client,
        dense_embedder=dense_embedder,
        sparse_embedder=sparse_embedder,
        image_embedder=image_embedder,
        image_fetcher=image_fetcher,
        row_fetcher=row_fetcher,
    )
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(3, len(plan.corpora)))) as executor:
        future_map = {
            executor.submit(
                worker_fn,
                corpus_plan=corpus,
                root=base_root,
                cancel_event=cancel_event,
                host_context=host_context,
                deps=deps,
                plan=plan,
            ): corpus.corpus
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
                    "documents_indexed": 0,
                    "warning_codes": ["worker_exception"],
                    "error": str(exc),
                }
    return {
        "site_id": plan.site_id,
        "site_slug": plan.site_slug,
        "corpora": results,
    }


def _default_worker(
    *,
    corpus_plan: RagCorpusPlan,
    root: Path,
    cancel_event: Event | None,
    host_context: HostExportContext | None,
    deps: _IndexingDeps,
    plan: RetrievalIndexPlan,
) -> dict[str, Any]:
    if _cancelled(cancel_event):
        return _cancelled_result()

    if corpus_plan.corpus == "faq":
        if str(corpus_plan.row_source_strategy or "").strip() == "host_python_fetch":
            return _ingest_faq_host_python_corpus(
                corpus_plan=corpus_plan,
                site_id=plan.site_id,
                cancel_event=cancel_event,
                host_context=host_context,
                deps=deps,
            )
        return _ingest_text_corpus(
            corpus_plan=corpus_plan,
            root=root,
            site_id=plan.site_id,
            cancel_event=cancel_event,
            deps=deps,
            chunker=chunk_faq_source,
            payload_builder=_build_faq_payload,
            sparse_enabled=True,
        )
    if corpus_plan.corpus == "policy":
        return _ingest_text_corpus(
            corpus_plan=corpus_plan,
            root=root,
            site_id=plan.site_id,
            cancel_event=cancel_event,
            deps=deps,
            chunker=chunk_policy_source,
            payload_builder=_build_policy_payload,
            sparse_enabled=True,
        )
    return _ingest_discovery_image_corpus(
        corpus_plan=corpus_plan,
        site_id=plan.site_id,
        cancel_event=cancel_event,
        host_context=host_context,
        deps=deps,
    )


def _ingest_faq_host_python_corpus(
    *,
    corpus_plan: RagCorpusPlan,
    site_id: str,
    cancel_event: Event | None,
    host_context: HostExportContext | None,
    deps: _IndexingDeps,
) -> dict[str, Any]:
    if _cancelled(cancel_event):
        return _cancelled_result()

    rows = _fetch_rows(
        corpus_plan=corpus_plan,
        host_context=host_context,
        cancel_event=cancel_event,
        deps=deps,
    )
    if _cancelled(cancel_event):
        return _cancelled_result()
    chunks = _build_faq_chunks_from_rows(rows)
    if not chunks:
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="no_indexable_chunks",
            warning_codes=["host_python_fetch_failed"],
        )

    texts = [str(chunk.get("text") or "").strip() for chunk in chunks]
    dense_vectors = deps.dense_embedder(texts)
    sparse_vectors = _maybe_embed_sparse(texts, deps=deps)
    client = _get_qdrant_client(deps)
    vector_size = len(dense_vectors[0]) if dense_vectors else 1024
    ensure_build_collection(
        collection_name=corpus_plan.build_collection,
        corpus=corpus_plan.corpus,
        vector_size=vector_size,
        client=client,
    )

    points: list[models.PointStruct] = []
    for index, chunk in enumerate(chunks):
        vector_payload: dict[str, Any] = {"": dense_vectors[index]}
        if sparse_vectors is not None:
            vector_payload["text-sparse"] = sparse_vectors[index]
        logical_id = str(chunk.get("chunk_id") or index)
        points.append(
            models.PointStruct(
                id=_build_point_id(site_id=site_id, corpus=corpus_plan.corpus, logical_id=logical_id),
                vector=vector_payload,
                payload=_build_faq_payload(chunk, site_id),
            )
        )
    upsert_points(
        collection_name=corpus_plan.build_collection,
        points=points,
        client=client,
    )
    swap_alias(
        alias_name=corpus_plan.collection_alias,
        build_collection=corpus_plan.build_collection,
        client=client,
    )
    documents_indexed = len(points)
    return _success_result(
        corpus_plan=corpus_plan,
        documents_indexed=documents_indexed,
        warning_codes=[],
        smoke_passed=documents_indexed >= max(1, corpus_plan.minimum_expected_documents),
    )


def _ingest_text_corpus(
    *,
    corpus_plan: RagCorpusPlan,
    root: Path,
    site_id: str,
    cancel_event: Event | None,
    deps: _IndexingDeps,
    chunker: Callable[[str | Path], list[dict[str, Any]]],
    payload_builder: Callable[[dict[str, Any], str], dict[str, Any]],
    sparse_enabled: bool,
) -> dict[str, Any]:
    if _cancelled(cancel_event):
        return _cancelled_result()
    available = [source for source in corpus_plan.sources if (root / source).exists()]
    if not available:
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="no_accessible_sources",
        )

    chunks: list[dict[str, Any]] = []
    warnings: list[str] = []
    for source in available:
        try:
            for chunk in chunker(root / source):
                chunks.append({"source_path": source, **chunk})
        except Exception:
            warnings.append("source_parse_failed")
    if not chunks:
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="no_indexable_chunks",
            warning_codes=warnings or ["no_indexable_chunks"],
        )

    texts = [str(chunk.get("text") or "").strip() for chunk in chunks]
    dense_vectors = deps.dense_embedder(texts)
    sparse_vectors = _maybe_embed_sparse(texts, deps=deps) if sparse_enabled else None
    client = _get_qdrant_client(deps)
    vector_size = len(dense_vectors[0]) if dense_vectors else 1024
    ensure_build_collection(
        collection_name=corpus_plan.build_collection,
        corpus=corpus_plan.corpus,
        vector_size=vector_size,
        client=client,
    )

    points: list[models.PointStruct] = []
    for index, chunk in enumerate(chunks):
        vector_payload: dict[str, Any] = {"": dense_vectors[index]}
        if sparse_vectors is not None:
            vector_payload["text-sparse"] = sparse_vectors[index]
        logical_id = str(chunk.get("chunk_id") or index)
        points.append(
            models.PointStruct(
                id=_build_point_id(site_id=site_id, corpus=corpus_plan.corpus, logical_id=logical_id),
                vector=vector_payload,
                payload=payload_builder(chunk, site_id),
            )
        )
    upsert_points(
        collection_name=corpus_plan.build_collection,
        points=points,
        client=client,
    )
    swap_alias(
        alias_name=corpus_plan.collection_alias,
        build_collection=corpus_plan.build_collection,
        client=client,
    )
    documents_indexed = len(points)
    return _success_result(
        corpus_plan=corpus_plan,
        documents_indexed=documents_indexed,
        warning_codes=warnings,
        smoke_passed=documents_indexed >= max(1, corpus_plan.minimum_expected_documents),
    )


def _ingest_discovery_image_corpus(
    *,
    corpus_plan: RagCorpusPlan,
    site_id: str,
    cancel_event: Event | None,
    host_context: HostExportContext | None,
    deps: _IndexingDeps,
) -> dict[str, Any]:
    if _cancelled(cancel_event):
        return _cancelled_result()
    if str(corpus_plan.row_source_strategy or "").strip() != "host_api_fetch":
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="unsupported_row_source_strategy",
            warning_codes=["unsupported_row_source_strategy"],
        )
    if str(corpus_plan.loader_strategy or "").strip() != "public_url_fetch":
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="unsupported_loader_strategy",
            warning_codes=["unsupported_loader_strategy"],
        )
    if not str(corpus_plan.row_source_endpoint or "").strip():
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="missing_row_source_endpoint",
            warning_codes=["missing_row_source_endpoint"],
        )

    rows = _fetch_rows(
        corpus_plan=corpus_plan,
        host_context=host_context,
        cancel_event=cancel_event,
        deps=deps,
    )
    rows = _ensure_resolved_image_rows(rows=rows, corpus_plan=corpus_plan)
    if _cancelled(cancel_event):
        return _cancelled_result()
    if not rows:
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="no_product_rows",
            warning_codes=["no_product_rows"],
        )

    image_entries: list[tuple[dict[str, Any], bytes]] = []
    warnings: list[str] = []
    fetcher = deps.image_fetcher or _fetch_image_bytes
    for row in rows:
        if _cancelled(cancel_event):
            return _cancelled_result()
        try:
            image_bytes = fetcher(str(row["resolved_image_url"]))
            image_entries.append((row, image_bytes))
        except Exception:
            warnings.append("image_fetch_failed")
    if not image_entries:
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="no_fetchable_images",
            warning_codes=warnings or ["no_fetchable_images"],
        )

    embedder = deps.image_embedder or _embed_image_bytes_batch
    vectors = embedder([payload for _, payload in image_entries])
    client = _get_qdrant_client(deps)
    vector_size = len(vectors[0]) if vectors else 512
    ensure_build_collection(
        collection_name=corpus_plan.build_collection,
        corpus=corpus_plan.corpus,
        vector_size=vector_size,
        client=client,
    )
    points: list[models.PointStruct] = []
    for index, (row, _image_bytes) in enumerate(image_entries):
        payload = {
            "product_id": int(row["product_id"]),
            "image_url": str(row["resolved_image_url"]),
            "site_id": site_id,
            "corpus": "discovery_image",
            **{
                key: value
                for key, value in row.items()
                if key not in {"product_id", "resolved_image_url"} and value is not None
            },
        }
        points.append(
            models.PointStruct(
                id=_build_point_id(
                    site_id=site_id,
                    corpus="discovery_image",
                    logical_id=f"{row['product_id']}:{index}",
                ),
                vector={"": vectors[index]},
                payload=payload,
            )
        )
    upsert_points(
        collection_name=corpus_plan.build_collection,
        points=points,
        client=client,
    )
    swap_alias(
        alias_name=corpus_plan.collection_alias,
        build_collection=corpus_plan.build_collection,
        client=client,
    )
    documents_indexed = len(points)
    return _success_result(
        corpus_plan=corpus_plan,
        documents_indexed=documents_indexed,
        warning_codes=warnings,
        smoke_passed=documents_indexed >= max(1, corpus_plan.minimum_expected_documents),
    )


def _fetch_rows(
    *,
    corpus_plan: RagCorpusPlan,
    host_context: HostExportContext | None,
    cancel_event: Event | None,
    deps: _IndexingDeps,
) -> list[dict[str, Any]]:
    if deps.row_fetcher is not None:
        return deps.row_fetcher(
            corpus_plan=corpus_plan,
            host_context=host_context,
            cancel_event=cancel_event,
        )
    strategy = str(corpus_plan.row_source_strategy or "").strip()
    if strategy == "host_api_fetch":
        return _fetch_product_rows_from_host_api(
            corpus_plan=corpus_plan,
            host_context=host_context,
            cancel_event=cancel_event,
        )
    if strategy == "host_python_fetch":
        return _fetch_rows_from_host_python(
            corpus_plan=corpus_plan,
            host_context=host_context,
            cancel_event=cancel_event,
        )
    return []


def _fetch_product_rows_from_host_api(
    *,
    corpus_plan: RagCorpusPlan,
    host_context: HostExportContext | None,
    cancel_event: Event | None,
) -> list[dict[str, Any]]:
    if host_context is None:
        raise RuntimeError("missing_host_export_context")
    while not host_context.export_ready.is_set():
        if _cancelled(cancel_event) or host_context.host_failed.is_set():
            return []
        host_context.export_ready.wait(timeout=0.2)
    if host_context.host_failed.is_set() or _cancelled(cancel_event):
        return []
    if (
        host_context.host_runtime_workspace is None
        or host_context.snapshot is None
        or host_context.integration_plan is None
    ):
        raise RuntimeError("host export context is incomplete")

    prep_result = prepare_backend_runtime(
        workspace=host_context.host_runtime_workspace,
        snapshot=host_context.snapshot,
    )
    if not prep_result.passed:
        raise RuntimeError(prep_result.failure_summary or "backend runtime prep failed")

    runtime_plan = build_backend_runtime_plan(
        workspace=host_context.host_runtime_workspace,
        snapshot=host_context.snapshot,
        plan=host_context.integration_plan,
        prep_result=prep_result,
    )
    runtime_state = launch_backend_runtime(runtime_plan)
    if not runtime_state.passed:
        raise RuntimeError(runtime_state.failure_summary or "backend runtime launch failed")

    try:
        base_url = f"http://127.0.0.1:{runtime_plan.listen_port}"
        return _paginate_product_rows(
            base_url=base_url,
            corpus_plan=corpus_plan,
            cancel_event=cancel_event,
        )
    finally:
        stop_backend_runtime(runtime_state)


def _fetch_rows_from_host_python(
    *,
    corpus_plan: RagCorpusPlan,
    host_context: HostExportContext | None,
    cancel_event: Event | None,
) -> list[dict[str, Any]]:
    if host_context is None:
        raise RuntimeError("missing_host_export_context")
    while not host_context.export_ready.is_set():
        if _cancelled(cancel_event) or host_context.host_failed.is_set():
            return []
        host_context.export_ready.wait(timeout=0.2)
    if host_context.host_failed.is_set() or _cancelled(cancel_event):
        return []
    if host_context.host_runtime_workspace is None or host_context.snapshot is None:
        raise RuntimeError("host export context is incomplete")

    prep_result = prepare_backend_runtime(
        workspace=host_context.host_runtime_workspace,
        snapshot=host_context.snapshot,
    )
    if not prep_result.passed:
        raise RuntimeError(prep_result.failure_summary or "backend runtime prep failed")

    module_name = str(corpus_plan.row_source_module or "").strip()
    callable_name = str(corpus_plan.row_source_callable or "").strip()
    if not module_name or not callable_name:
        raise RuntimeError("host python fetch contract is incomplete")

    workspace = Path(host_context.host_runtime_workspace).resolve()
    backend_root = workspace / "backend" if (workspace / "backend").exists() else workspace
    script = (
        "import importlib, json, sys; "
        f"sys.path.insert(0, {str(backend_root)!r}); "
        f"module = importlib.import_module({module_name!r}); "
        f"callable_obj = getattr(module, {callable_name!r}); "
        "rows = callable_obj(); "
        "print(json.dumps(rows, ensure_ascii=False))"
    )
    result = subprocess.run(
        [str(prep_result.python_executable or ""), "-c", script],
        cwd=backend_root,
        env=build_backend_subprocess_env(backend_root=backend_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "host python fetch failed").strip())
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("host python fetch returned invalid json") from exc
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _paginate_product_rows(
    *,
    base_url: str,
    corpus_plan: RagCorpusPlan,
    cancel_event: Event | None,
) -> list[dict[str, Any]]:
    strategy = dict(corpus_plan.pagination_strategy or {})
    endpoint = str(corpus_plan.row_source_endpoint or "").strip()
    if not endpoint:
        return []
    page_param = str(strategy.get("page_param") or "page")
    page_size_param = str(strategy.get("page_size_param") or "page_size")
    page_size = int(strategy.get("page_size") or 100)
    page = 1
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        while page <= 100:
            if _cancelled(cancel_event):
                return []
            response = client.get(
                urljoin(base_url, endpoint),
                params={page_param: page, page_size_param: page_size},
            )
            response.raise_for_status()
            payload = response.json()
            batch = _extract_product_rows(payload)
            if not batch:
                break
            normalized_batch = _normalize_product_rows(
                rows=batch,
                row_id_field=str(corpus_plan.row_id_field or "product_id"),
                row_image_url_field=str(corpus_plan.row_image_url_field or "image_url"),
                base_url=base_url,
            )
            new_rows = [row for row in normalized_batch if str(row["product_id"]) not in seen_ids]
            if not new_rows:
                break
            rows.extend(new_rows)
            seen_ids.update(str(row["product_id"]) for row in new_rows)
            page += 1
    return rows


def _extract_product_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("products", "items", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_product_rows(value)
            if nested:
                return nested
    return []


def _normalize_product_rows(
    *,
    rows: list[dict[str, Any]],
    row_id_field: str,
    row_image_url_field: str,
    base_url: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        product_id = row.get(row_id_field)
        image_url = row.get(row_image_url_field)
        if product_id is None or not str(image_url or "").strip():
            continue
        resolved_image_url = urljoin(base_url, str(image_url).strip())
        normalized.append(
            {
                **row,
                "product_id": product_id,
                "resolved_image_url": resolved_image_url,
            }
        )
    return normalized


def _ensure_resolved_image_rows(
    *,
    rows: list[dict[str, Any]],
    corpus_plan: RagCorpusPlan,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    row_id_field = str(corpus_plan.row_id_field or "product_id")
    row_image_url_field = str(corpus_plan.row_image_url_field or "image_url")
    for row in rows:
        product_id = row.get("product_id", row.get(row_id_field))
        image_url = row.get("resolved_image_url", row.get(row_image_url_field))
        if product_id is None or not str(image_url or "").strip():
            continue
        normalized.append(
            {
                **row,
                "product_id": product_id,
                "resolved_image_url": str(image_url).strip(),
            }
        )
    return normalized


def _build_faq_payload(chunk: dict[str, Any], site_id: str) -> dict[str, Any]:
    payload = {
        "chunk_id": str(chunk.get("chunk_id") or "").strip(),
        "question": str(chunk.get("question") or "").strip(),
        "answer": str(chunk.get("answer") or "").strip(),
        "text": str(chunk.get("text") or "").strip(),
        "source_path": str(chunk.get("source_path") or "").strip(),
        "site_id": site_id,
        "corpus": "faq",
    }
    if str(chunk.get("main_category") or "").strip():
        payload["main_category"] = str(chunk.get("main_category")).strip()
    if str(chunk.get("sub_category") or "").strip():
        payload["sub_category"] = str(chunk.get("sub_category")).strip()
    return payload


def _build_policy_payload(chunk: dict[str, Any], site_id: str) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.get("chunk_id") or "").strip(),
        "text": str(chunk.get("text") or "").strip(),
        "clause_title": str(chunk.get("heading") or "").strip() or "document",
        "source_path": str(chunk.get("source_path") or "").strip(),
        "site_id": site_id,
        "corpus": "policy",
        "category": str(chunk.get("heading") or "").strip() or "document",
    }


def _build_faq_chunks_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        question = str(row.get("question") or "").strip()
        answer = str(row.get("answer") or "").strip()
        if not question or not answer:
            continue
        category = str(row.get("category") or row.get("main_category") or "").strip()
        chunks.append(
            {
                "chunk_id": str(row.get("faq_id") or row.get("chunk_id") or f"faq-{index:04d}"),
                "question": question,
                "answer": answer,
                "text": f"질문: {question}\n답변: {answer}",
                "main_category": category,
                "source_path": str(row.get("source_path") or "").strip(),
            }
        )
    return chunks


def _build_point_id(*, site_id: str, corpus: str, logical_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{site_id}:{corpus}:{logical_id}"))


def _maybe_embed_sparse(
    texts: list[str],
    *,
    deps: _IndexingDeps,
) -> list[models.SparseVector] | None:
    sparse_embedder = deps.sparse_embedder or _default_sparse_embedder
    try:
        return sparse_embedder(texts)
    except Exception:
        return None


def _default_sparse_embedder(texts: list[str]) -> list[models.SparseVector]:
    from fastembed import SparseTextEmbedding

    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    embedded = list(sparse_model.embed(texts))
    return [
        models.SparseVector(
            indices=item.indices.tolist(),
            values=item.values.tolist(),
        )
        for item in embedded
    ]


def _embed_image_bytes_batch(images: list[bytes]) -> list[list[float]]:
    from chatbot.src.tools.image_search_tools import _get_clip_resources, _resolve_device
    import torch

    device = _resolve_device()
    processor, model = _get_clip_resources(device)
    pil_images = [Image.open(BytesIO(image_bytes)).convert("RGB") for image_bytes in images]
    inputs = processor(images=pil_images, return_tensors="pt", padding=True)  # type: ignore[call-arg]
    inputs = {key: value.to(device) for key, value in inputs.items()}
    with torch.no_grad():
        features = model.get_image_features(**inputs)
    normalized = features / features.norm(dim=-1, keepdim=True)
    return normalized.cpu().to(torch.float32).tolist()


def _fetch_image_bytes(image_url: str) -> bytes:
    response = httpx.get(image_url, timeout=20.0, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _get_qdrant_client(deps: _IndexingDeps) -> object:
    if deps.qdrant_client is not None:
        return deps.qdrant_client
    from chatbot.src.infrastructure.qdrant import get_qdrant_client

    return get_qdrant_client()


def _cancelled(cancel_event: Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _cancelled_result() -> dict[str, Any]:
    return {
        "status": "aborted_by_host_failure",
        "enabled": False,
        "documents_indexed": 0,
        "warning_codes": [],
        "reason": "host_lane_failed",
        "alias_swapped": False,
        "smoke_passed": False,
    }


def _failure_result(
    *,
    corpus_plan: RagCorpusPlan,
    reason: str,
    warning_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "enabled": False,
        "documents_indexed": 0,
        "collection_alias": corpus_plan.collection_alias,
        "build_collection": corpus_plan.build_collection,
        "loader_strategy": corpus_plan.loader_strategy,
        "warning_codes": list(warning_codes or []),
        "reason": reason,
        "alias_swapped": False,
        "smoke_passed": False,
    }


def _success_result(
    *,
    corpus_plan: RagCorpusPlan,
    documents_indexed: int,
    warning_codes: list[str],
    smoke_passed: bool,
) -> dict[str, Any]:
    return {
        "status": "completed",
        "enabled": documents_indexed >= 1,
        "documents_indexed": documents_indexed,
        "collection_alias": corpus_plan.collection_alias,
        "build_collection": corpus_plan.build_collection,
        "loader_strategy": corpus_plan.loader_strategy,
        "warning_codes": list(dict.fromkeys(warning_codes)),
        "alias_swapped": True,
        "smoke_passed": bool(smoke_passed),
    }
