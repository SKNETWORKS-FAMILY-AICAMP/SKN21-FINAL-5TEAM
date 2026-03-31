from __future__ import annotations

import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
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
from chatbot.src.onboarding_v2.eventing import EventCallback, ProgressHeartbeat, emit_stage_event
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


class _IndexingError(RuntimeError):
    def __init__(
        self,
        reason: str,
        *,
        warning_codes: list[str] | None = None,
        error: str | None = None,
        log_paths: dict[str, str] | None = None,
    ) -> None:
        super().__init__(error or reason)
        self.reason = reason
        self.warning_codes = list(warning_codes or [])
        self.error = str(error or reason)
        self.log_paths = dict(log_paths or {})


@dataclass(slots=True)
class _WorkerEventSession:
    corpus_plan: RagCorpusPlan
    event_callback: EventCallback | None
    heartbeat_interval_s: float
    _lock: Lock = field(default_factory=Lock)
    _progress: ProgressHeartbeat | None = None
    _started: bool = False
    _started_at: float = field(default_factory=time.monotonic)

    def emit_started_if_needed(self) -> None:
        if self.event_callback is None:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
            self._started_at = time.monotonic()
            emit_stage_event(
                self.event_callback,
                phase="worker_start",
                event_type="retrieval_worker_started",
                summary=f"{self.corpus_plan.corpus} retrieval worker started",
                details=self._details(status="running", elapsed_ms=0),
            )
            self._progress = ProgressHeartbeat(
                event_callback=self.event_callback,
                phase="worker_progress",
                event_type="retrieval_worker_progress",
                summary=f"{self.corpus_plan.corpus} retrieval worker still running",
                heartbeat_interval_s=self.heartbeat_interval_s,
                details_factory=lambda _elapsed_ms: self._details(
                    status="running",
                    elapsed_ms=int((time.monotonic() - self._started_at) * 1000),
                ),
            ).start()

    def emit_finished(self, result: dict[str, Any]) -> None:
        self.stop_progress()
        if self.event_callback is None:
            return
        status = str(result.get("status") or "failed")
        if status == "completed":
            event_type = "retrieval_worker_completed"
            summary = f"{self.corpus_plan.corpus} retrieval worker completed"
        elif status == "aborted_by_host_failure":
            event_type = "retrieval_worker_cancelled"
            summary = f"{self.corpus_plan.corpus} retrieval worker cancelled"
        else:
            event_type = "retrieval_worker_failed"
            summary = f"{self.corpus_plan.corpus} retrieval worker failed"
        details = self._details(
            status=status,
            elapsed_ms=int((time.monotonic() - self._started_at) * 1000),
        )
        details.update({key: value for key, value in result.items() if key not in {"collection_alias", "loader_strategy"}})
        emit_stage_event(
            self.event_callback,
            phase="worker_finish",
            event_type=event_type,
            summary=summary,
            details=details,
        )

    def stop_progress(self) -> None:
        with self._lock:
            if self._progress is not None:
                self._progress.stop()
                self._progress = None

    def _details(self, *, status: str, elapsed_ms: int) -> dict[str, Any]:
        return {
            "corpus": self.corpus_plan.corpus,
            "loader_strategy": self.corpus_plan.loader_strategy,
            "collection_alias": self.corpus_plan.collection_alias,
            "status": status,
            "elapsed_ms": int(elapsed_ms),
        }


@dataclass(slots=True)
class _SharedHostRuntime:
    host_context: HostExportContext | None
    cancel_event: Event | None
    live_logs_root: Path | None = None
    event_callback: EventCallback | None = None
    heartbeat_interval_s: float = 5.0
    worker_sessions: dict[str, _WorkerEventSession] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    _prep_result: Any | None = None
    _runtime_plan: Any | None = None
    _runtime_state: Any | None = None
    _closed: bool = False

    def ensure_prepared(self, *, corpus_plan: RagCorpusPlan | None = None) -> tuple[Any, Path]:
        host_context = self._wait_for_export_ready(corpus_plan=corpus_plan)
        workspace = Path(host_context.host_runtime_workspace or "").resolve()
        backend_root = workspace / "backend" if (workspace / "backend").exists() else workspace
        if self._prep_result is None:
            with self._lock:
                if self._prep_result is None:
                    prep_logs_root = self.live_logs_root / "host-prep" if self.live_logs_root is not None else None
                    self._prep_result = prepare_backend_runtime(
                        workspace=workspace,
                        snapshot=host_context.snapshot,
                        live_logs_root=prep_logs_root,
                    )
        prep_result = self._prep_result
        if not getattr(prep_result, "passed", False):
            raise _IndexingError(
                "backend runtime prep failed",
                warning_codes=["host_runtime_prep_failed"],
                error=str(getattr(prep_result, "failure_summary", "") or "backend runtime prep failed"),
                log_paths=dict(getattr(prep_result, "live_log_paths", {}) or {}),
            )
        return prep_result, backend_root

    def ensure_runtime(self, *, corpus_plan: RagCorpusPlan | None = None) -> tuple[Any, Any]:
        prep_result, _backend_root = self.ensure_prepared(corpus_plan=corpus_plan)
        host_context = self._wait_for_export_ready(
            require_integration_plan=True,
            corpus_plan=corpus_plan,
        )
        if self._runtime_state is None:
            with self._lock:
                if self._runtime_state is None:
                    self._runtime_plan = build_backend_runtime_plan(
                        workspace=host_context.host_runtime_workspace,
                        snapshot=host_context.snapshot,
                        plan=host_context.integration_plan,
                        prep_result=prep_result,
                    )
                    runtime_log_path = (
                        self.live_logs_root / "host-runtime.log" if self.live_logs_root is not None else None
                    )
                    self._runtime_state = launch_backend_runtime(
                        self._runtime_plan,
                        log_path=runtime_log_path,
                    )
        runtime_state = self._runtime_state
        if not getattr(runtime_state, "passed", False):
            log_paths: dict[str, str] = {}
            launcher_log_path = str(getattr(runtime_state, "launcher_log_path", "") or "").strip()
            if launcher_log_path:
                log_paths["launcher"] = launcher_log_path
            raise _IndexingError(
                "backend runtime boot failed",
                warning_codes=["host_runtime_boot_failed"],
                error=str(getattr(runtime_state, "failure_summary", "") or "backend runtime boot failed"),
                log_paths=log_paths,
            )
        return self._runtime_plan, runtime_state

    def close(self) -> None:
        runtime_state = self._runtime_state
        if runtime_state is None:
            return
        with self._lock:
            if self._closed:
                return
            stop_backend_runtime(runtime_state)
            self._closed = True

    def _wait_for_export_ready(
        self,
        *,
        require_integration_plan: bool = False,
        corpus_plan: RagCorpusPlan | None = None,
    ) -> HostExportContext:
        host_context = self.host_context
        if host_context is None:
            raise _IndexingError(
                "missing_host_export_context",
                warning_codes=["host_runtime_context_missing"],
            )
        waiting_heartbeat: ProgressHeartbeat | None = None
        if corpus_plan is not None and self.event_callback is not None and not host_context.export_ready.is_set():
            emit_stage_event(
                self.event_callback,
                phase="worker_wait",
                event_type="retrieval_worker_waiting_on_export",
                summary=f"{corpus_plan.corpus} retrieval worker waiting on export",
                details={
                    "corpus": corpus_plan.corpus,
                    "loader_strategy": corpus_plan.loader_strategy,
                    "status": "waiting_on_export",
                    "elapsed_ms": 0,
                },
            )
            waiting_heartbeat = ProgressHeartbeat(
                event_callback=self.event_callback,
                phase="worker_wait",
                event_type="retrieval_worker_waiting_on_export",
                summary=f"{corpus_plan.corpus} retrieval worker waiting on export",
                heartbeat_interval_s=self.heartbeat_interval_s,
                details_factory=lambda elapsed_ms: {
                    "corpus": corpus_plan.corpus,
                    "loader_strategy": corpus_plan.loader_strategy,
                    "status": "waiting_on_export",
                    "elapsed_ms": elapsed_ms,
                },
            ).start()
        while not host_context.export_ready.is_set():
            if _cancelled(self.cancel_event) or host_context.host_failed.is_set():
                if waiting_heartbeat is not None:
                    waiting_heartbeat.stop()
                raise _IndexingError(
                    "host export failed",
                    warning_codes=["host_lane_failed"],
                )
            host_context.export_ready.wait(timeout=0.2)
        if waiting_heartbeat is not None:
            waiting_heartbeat.stop()
        if host_context.host_failed.is_set() or _cancelled(self.cancel_event):
            raise _IndexingError(
                "host export failed",
                warning_codes=["host_lane_failed"],
            )
        if host_context.host_runtime_workspace is None or host_context.snapshot is None:
            raise _IndexingError(
                "host export context is incomplete",
                warning_codes=["host_runtime_context_missing"],
            )
        if require_integration_plan and host_context.integration_plan is None:
            raise _IndexingError(
                "host export context is incomplete",
                warning_codes=["host_runtime_context_missing"],
            )
        if corpus_plan is not None:
            self._mark_worker_started(corpus_plan)
        return host_context

    def _mark_worker_started(self, corpus_plan: RagCorpusPlan) -> None:
        session = self.worker_sessions.get(corpus_plan.corpus)
        if session is not None:
            session.emit_started_if_needed()


@dataclass(slots=True)
class _IndexingDeps:
    qdrant_client: object | None = None
    dense_embedder: Callable[[list[str]], list[list[float]]] = embed_texts
    sparse_embedder: Callable[[list[str]], list[models.SparseVector]] | None = None
    image_embedder: Callable[[list[bytes]], list[list[float]]] | None = None
    image_fetcher: Callable[[str], bytes] | None = None
    row_fetcher: Callable[..., list[dict[str, Any]]] | None = None
    shared_host_runtime: _SharedHostRuntime | None = None


def _corpus_requires_host_export(corpus_plan: RagCorpusPlan) -> bool:
    return str(corpus_plan.row_source_strategy or "").strip() in {"host_api_fetch", "host_python_fetch"}


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
    sparse_text_paths, payload_paths, row_enrichment_strategy, auxiliary_relation_hints = (
        _resolve_discovery_image_enrichment_contract(
            records=records,
            row_source_strategy="host_api_fetch",
            image_field=image_field or "image_url",
        )
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
        dense_image_field=image_field or "image_url",
        sparse_text_paths=sparse_text_paths,
        payload_paths=payload_paths,
        row_enrichment_strategy=row_enrichment_strategy,
        auxiliary_relation_hints=auxiliary_relation_hints,
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


def _resolve_discovery_image_enrichment_contract(
    *,
    records: list[Any],
    row_source_strategy: str | None,
    image_field: str,
) -> tuple[list[str], list[str], str | None, list[dict[str, Any]]]:
    sparse_text_paths: list[str] = []
    payload_paths: list[str] = []
    auxiliary_relation_hints: list[dict[str, Any]] = []

    def _append_unique(target: list[str], value: str) -> None:
        normalized = str(value or "").strip()
        if normalized and normalized not in target:
            target.append(normalized)

    for record in records:
        details = getattr(record, "details", {}) or {}
        for field_name in details.get("text_field_candidates") or []:
            _append_unique(sparse_text_paths, str(field_name))
        for path in details.get("nested_text_paths") or []:
            _append_unique(sparse_text_paths, str(path))
        for field_name in details.get("payload_field_candidates") or []:
            _append_unique(payload_paths, str(field_name))
        for hint in details.get("auxiliary_relation_hints") or []:
            if isinstance(hint, dict):
                auxiliary_relation_hints.append(dict(hint))

    for hint in auxiliary_relation_hints:
        merge_as = str(hint.get("merge_as") or "").strip()
        for field_name in hint.get("text_fields") or []:
            if merge_as:
                _append_unique(sparse_text_paths, f"{merge_as}.{field_name}")
        if merge_as:
            _append_unique(payload_paths, merge_as)

    for required in ("product_id", image_field, "name", "brand", "category", "description", "price"):
        _append_unique(payload_paths, required)
    for preferred in ("name", "brand", "category", "description"):
        _append_unique(sparse_text_paths, preferred)

    row_enrichment_strategy = None
    if auxiliary_relation_hints and row_source_strategy == "host_python_fetch":
        row_enrichment_strategy = "host_python_wrapper"
    elif sparse_text_paths or payload_paths:
        row_enrichment_strategy = "row_contract"

    return sparse_text_paths, payload_paths, row_enrichment_strategy, auxiliary_relation_hints


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
    live_logs_root: str | Path | None = None,
    event_callback: EventCallback | None = None,
    heartbeat_interval_s: float = 5.0,
) -> dict[str, Any]:
    base_root = Path(root)
    worker_fn = worker or _default_worker
    worker_sessions = {
        corpus.corpus: _WorkerEventSession(
            corpus_plan=corpus,
            event_callback=event_callback,
            heartbeat_interval_s=heartbeat_interval_s,
        )
        for corpus in plan.corpora
    }
    shared_host_runtime = _SharedHostRuntime(
        host_context=host_context,
        cancel_event=cancel_event,
        live_logs_root=Path(live_logs_root).resolve() if live_logs_root is not None else None,
        event_callback=event_callback,
        heartbeat_interval_s=heartbeat_interval_s,
        worker_sessions=worker_sessions,
    )
    deps = _IndexingDeps(
        qdrant_client=qdrant_client,
        dense_embedder=dense_embedder,
        sparse_embedder=sparse_embedder,
        image_embedder=image_embedder,
        image_fetcher=image_fetcher,
        row_fetcher=row_fetcher,
        shared_host_runtime=shared_host_runtime,
    )
    results: dict[str, Any] = {}

    def _run_worker(corpus_plan: RagCorpusPlan) -> dict[str, Any]:
        session = worker_sessions[corpus_plan.corpus]
        if not _corpus_requires_host_export(corpus_plan):
            session.emit_started_if_needed()
        return worker_fn(
            corpus_plan=corpus_plan,
            root=base_root,
            cancel_event=cancel_event,
            host_context=host_context,
            deps=deps,
            plan=plan,
        )

    try:
        with ThreadPoolExecutor(max_workers=max(1, min(3, len(plan.corpora)))) as executor:
            future_map = {
                executor.submit(
                    _run_worker,
                    corpus,
                ): corpus
                for corpus in plan.corpora
            }
            for future in as_completed(future_map):
                corpus_plan = future_map[future]
                session = worker_sessions[corpus_plan.corpus]
                try:
                    result = future.result()
                    results[corpus_plan.corpus] = _coerce_cancelled_result(
                        result=result,
                        corpus_plan=corpus_plan,
                        cancel_event=cancel_event,
                    )
                except _IndexingError as exc:
                    if _cancelled(cancel_event) or "host_lane_failed" in exc.warning_codes:
                        results[corpus_plan.corpus] = _cancelled_result(corpus_plan=corpus_plan)
                    else:
                        results[corpus_plan.corpus] = _failure_result(
                            corpus_plan=corpus_plan,
                            reason=exc.reason,
                            warning_codes=exc.warning_codes,
                            error=exc.error,
                            log_paths=exc.log_paths,
                        )
                except Exception as exc:
                    if _cancelled(cancel_event):
                        results[corpus_plan.corpus] = _cancelled_result(corpus_plan=corpus_plan)
                    else:
                        results[corpus_plan.corpus] = _failure_result(
                            corpus_plan=corpus_plan,
                            reason="worker_exception",
                            warning_codes=["worker_exception"],
                            error=str(exc),
                        )
                finally:
                    session.stop_progress()
        for corpus_plan in plan.corpora:
            session = worker_sessions[corpus_plan.corpus]
            result = _coerce_cancelled_result(
                result=results.get(corpus_plan.corpus) or _cancelled_result(corpus_plan=corpus_plan),
                corpus_plan=corpus_plan,
                cancel_event=cancel_event,
            )
            results[corpus_plan.corpus] = result
            session.emit_finished(result)
    finally:
        for session in worker_sessions.values():
            session.stop_progress()
        shared_host_runtime.close()
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
        return _cancelled_result(corpus_plan=corpus_plan)

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
        return _cancelled_result(corpus_plan=corpus_plan)

    rows = _fetch_rows(
        corpus_plan=corpus_plan,
        host_context=host_context,
        cancel_event=cancel_event,
        deps=deps,
    )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    chunks = _build_faq_chunks_from_rows(rows)
    if not chunks:
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="no_indexable_chunks",
            warning_codes=["host_python_fetch_failed"],
        )

    texts = [str(chunk.get("text") or "").strip() for chunk in chunks]
    dense_vectors = deps.dense_embedder(texts)
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    sparse_vectors = _maybe_embed_sparse(texts, deps=deps)
    client = _get_qdrant_client(deps)
    vector_size = len(dense_vectors[0]) if dense_vectors else 1024
    ensure_build_collection(
        collection_name=corpus_plan.build_collection,
        corpus=corpus_plan.corpus,
        vector_size=vector_size,
        client=client,
    )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)

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
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    upsert_points(
        collection_name=corpus_plan.build_collection,
        points=points,
        client=client,
    )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
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
        return _cancelled_result(corpus_plan=corpus_plan)
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
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    sparse_vectors = _maybe_embed_sparse(texts, deps=deps) if sparse_enabled else None
    client = _get_qdrant_client(deps)
    vector_size = len(dense_vectors[0]) if dense_vectors else 1024
    ensure_build_collection(
        collection_name=corpus_plan.build_collection,
        corpus=corpus_plan.corpus,
        vector_size=vector_size,
        client=client,
    )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)

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
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    upsert_points(
        collection_name=corpus_plan.build_collection,
        points=points,
        client=client,
    )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
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
        return _cancelled_result(corpus_plan=corpus_plan)
    row_source_strategy = str(corpus_plan.row_source_strategy or "").strip()
    if row_source_strategy not in {"host_api_fetch", "host_python_fetch"}:
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
    if row_source_strategy == "host_api_fetch" and not str(corpus_plan.row_source_endpoint or "").strip():
        return _failure_result(
            corpus_plan=corpus_plan,
            reason="missing_row_source_endpoint",
            warning_codes=["missing_row_source_endpoint"],
        )

    raw_rows = _fetch_raw_rows(
        corpus_plan=corpus_plan,
        host_context=host_context,
        cancel_event=cancel_event,
        deps=deps,
    )
    rows = _ensure_resolved_image_rows(rows=raw_rows, corpus_plan=corpus_plan)
    diagnostics: dict[str, Any] = {
        "preseed_attempted": False,
        "preseed_reason": None,
        "preseed_outcome": "not_needed",
    }
    if not raw_rows:
        diagnostics.update(
            _run_discovery_image_seed_script(
                corpus_plan=corpus_plan,
                host_context=host_context,
                cancel_event=cancel_event,
                deps=deps,
                reason="no_product_rows",
            )
        )
        if diagnostics.get("preseed_outcome") == "failed":
            return _with_optional_diagnostics(
                _failure_result(
                    corpus_plan=corpus_plan,
                    reason="fixture_seed_failed",
                    warning_codes=["fixture_seed_failed"],
                    error=str(diagnostics.get("preseed_error") or "seed failed"),
                ),
                diagnostics,
            )
        raw_rows = _fetch_raw_rows(
            corpus_plan=corpus_plan,
            host_context=host_context,
            cancel_event=cancel_event,
            deps=deps,
        )
        rows = _ensure_resolved_image_rows(rows=raw_rows, corpus_plan=corpus_plan)
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    diagnostics["preseed_raw_row_count"] = len(raw_rows)
    diagnostics["preseed_indexable_row_count"] = len(rows)
    if not raw_rows:
        return _with_optional_diagnostics(
            _skipped_result(
                corpus_plan=corpus_plan,
                reason="no_product_rows",
                warning_codes=["no_product_rows"],
            ),
            diagnostics,
        )
    if not rows:
        diagnostics["preseed_attempted"] = bool(diagnostics.get("preseed_attempted"))
        if not diagnostics["preseed_attempted"]:
            diagnostics["preseed_reason"] = "raw_product_rows_present"
            diagnostics["preseed_outcome"] = "raw_product_rows_present"
        else:
            diagnostics["preseed_reason"] = diagnostics.get("preseed_reason") or "raw_product_rows_present"
            diagnostics["preseed_outcome"] = diagnostics.get("preseed_outcome") or "raw_product_rows_present"
        return _with_optional_diagnostics(
            _skipped_result(
                corpus_plan=corpus_plan,
                reason="no_indexable_image_rows",
                warning_codes=["no_indexable_image_rows"],
            ),
            diagnostics,
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
    sparse_texts = [
        _build_discovery_image_sparse_text(row=row, corpus_plan=corpus_plan) for row, _ in image_entries
    ]
    sparse_vectors = _maybe_embed_sparse(sparse_texts, deps=deps)
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    client = _get_qdrant_client(deps)
    vector_size = len(vectors[0]) if vectors else 512
    ensure_build_collection(
        collection_name=corpus_plan.build_collection,
        corpus=corpus_plan.corpus,
        vector_size=vector_size,
        client=client,
    )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    points: list[models.PointStruct] = []
    for index, (row, _image_bytes) in enumerate(image_entries):
        retrieval_text = sparse_texts[index]
        payload = _build_discovery_image_payload(
            row=row,
            corpus_plan=corpus_plan,
            site_id=site_id,
            retrieval_text=retrieval_text,
        )
        vector_payload: dict[str, Any] = {"": vectors[index]}
        if sparse_vectors is not None:
            vector_payload["text-sparse"] = sparse_vectors[index]
        points.append(
            models.PointStruct(
                id=_build_point_id(
                    site_id=site_id,
                    corpus="discovery_image",
                    logical_id=f"{row['product_id']}:{index}",
                ),
                vector=vector_payload,
                payload=payload,
            )
        )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    diagnostics["documents_prepared"] = len(points)
    diagnostics["batches_attempted"] = 0
    diagnostics["batches_completed"] = 0
    diagnostics["last_successful_product_id"] = None
    batch_size = _discovery_image_batch_size()
    try:
        for batch_start in range(0, len(points), batch_size):
            batch = points[batch_start : batch_start + batch_size]
            diagnostics["batches_attempted"] += 1
            upsert_points(
                collection_name=corpus_plan.build_collection,
                points=batch,
                client=client,
            )
            diagnostics["batches_completed"] += 1
            last_payload = dict(getattr(batch[-1], "payload", {}) or {})
            if last_payload.get("product_id") not in (None, ""):
                diagnostics["last_successful_product_id"] = last_payload.get("product_id")
    except Exception as exc:
        return _with_optional_diagnostics(
            _failure_result(
                corpus_plan=corpus_plan,
                reason="worker_exception",
                warning_codes=["worker_exception"],
                error=str(exc),
            ),
            diagnostics,
        )
    if _cancelled(cancel_event):
        return _cancelled_result(corpus_plan=corpus_plan)
    swap_alias(
        alias_name=corpus_plan.collection_alias,
        build_collection=corpus_plan.build_collection,
        client=client,
    )
    documents_indexed = len(points)
    return _with_optional_diagnostics(
        _success_result(
            corpus_plan=corpus_plan,
            documents_indexed=documents_indexed,
            warning_codes=warnings,
            smoke_passed=documents_indexed >= max(1, corpus_plan.minimum_expected_documents),
        ),
        diagnostics,
    )


def _discovery_image_batch_size() -> int:
    raw_value = str(os.environ.get("ONBOARDING_DISCOVERY_IMAGE_UPSERT_BATCH_SIZE") or "").strip()
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 32


def _fetch_rows(
    *,
    corpus_plan: RagCorpusPlan,
    host_context: HostExportContext | None,
    cancel_event: Event | None,
    deps: _IndexingDeps,
) -> list[dict[str, Any]]:
    raw_rows = _fetch_raw_rows(
        corpus_plan=corpus_plan,
        host_context=host_context,
        cancel_event=cancel_event,
        deps=deps,
    )
    strategy = str(corpus_plan.row_source_strategy or "").strip()
    if strategy == "host_api_fetch":
        return _ensure_resolved_image_rows(rows=raw_rows, corpus_plan=corpus_plan)
    return raw_rows


def _fetch_raw_rows(
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
            deps=deps,
        )
    if strategy == "host_python_fetch":
        return _fetch_rows_from_host_python(
            corpus_plan=corpus_plan,
            host_context=host_context,
            cancel_event=cancel_event,
            deps=deps,
        )
    return []


def _fetch_product_rows_from_host_api(
    *,
    corpus_plan: RagCorpusPlan,
    host_context: HostExportContext | None,
    cancel_event: Event | None,
    deps: _IndexingDeps,
) -> list[dict[str, Any]]:
    shared_host_runtime = deps.shared_host_runtime
    if shared_host_runtime is None:
        raise _IndexingError(
            "missing_host_runtime_session",
            warning_codes=["host_runtime_context_missing"],
        )
    runtime_plan, _runtime_state = shared_host_runtime.ensure_runtime(corpus_plan=corpus_plan)
    try:
        base_url = f"http://127.0.0.1:{runtime_plan.listen_port}"
        rows = _paginate_product_rows(
            base_url=base_url,
            corpus_plan=corpus_plan,
            cancel_event=cancel_event,
        )
        return [{**row, "__host_base_url": base_url} for row in rows]
    except httpx.HTTPError as exc:
        raise _IndexingError(
            "row source fetch failed",
            warning_codes=["row_source_fetch_failed"],
            error=str(exc),
        ) from exc


def _fetch_rows_from_host_python(
    *,
    corpus_plan: RagCorpusPlan,
    host_context: HostExportContext | None,
    cancel_event: Event | None,
    deps: _IndexingDeps,
) -> list[dict[str, Any]]:
    shared_host_runtime = deps.shared_host_runtime
    if shared_host_runtime is None:
        raise _IndexingError(
            "missing_host_runtime_session",
            warning_codes=["host_runtime_context_missing"],
        )
    prep_result, backend_root = shared_host_runtime.ensure_prepared(corpus_plan=corpus_plan)

    module_name = str(corpus_plan.row_source_module or "").strip()
    callable_name = str(corpus_plan.row_source_callable or "").strip()
    if not module_name or not callable_name:
        raise _IndexingError(
            "host python fetch contract is incomplete",
            warning_codes=["host_python_fetch_failed"],
        )
    auxiliary_relation_hints = _sanitize_auxiliary_relation_hints(corpus_plan.auxiliary_relation_hints)
    script = "\n".join(
        [
            "import importlib, json, sys",
            f"sys.path.insert(0, {str(backend_root)!r})",
            "try:",
            "    import oracledb",
            "    defaults = getattr(oracledb, 'defaults', None)",
            "    if defaults is not None:",
            "        defaults.fetch_lobs = False",
            "except Exception:",
            "    pass",
            "def _json_default(obj):",
            "    reader = getattr(obj, 'read', None)",
            "    if callable(reader):",
            "        try:",
            "            return reader()",
            "        except Exception:",
            "            pass",
            "    isoformat = getattr(obj, 'isoformat', None)",
            "    if callable(isoformat):",
            "        try:",
            "            return isoformat()",
            "        except Exception:",
            "            pass",
            "    return str(obj)",
            "def _merge_auxiliary_rows(rows, hints, key_field):",
            "    if not rows or not hints:",
            "        return rows",
            "    from models import get_connection",
            "    conn = get_connection()",
            "    cursor = conn.cursor()",
            "    try:",
            "        for hint in hints:",
            "            table_name = hint.get('table_name')",
            "            merge_as = hint.get('merge_as') or table_name",
            "            relation_key = hint.get('key_field') or key_field",
            "            text_fields = [item for item in hint.get('text_fields') or [] if item]",
            "            if not table_name or not merge_as or not relation_key or not text_fields:",
            "                continue",
            "            query = f\"SELECT {relation_key}, {', '.join(text_fields)} FROM {table_name}\"",
            "            cursor.execute(query)",
            "            merged = {}",
            "            for record in cursor.fetchall():",
            "                related_key = record[0]",
            "                payload = {}",
            "                for index, field_name in enumerate(text_fields, start=1):",
            "                    value = record[index]",
            "                    normalized = _json_default(value) if value is not None else None",
            "                    if normalized not in (None, ''):",
            "                        payload[field_name] = normalized",
            "                if payload:",
            "                    merged[str(related_key)] = payload",
            "            for row in rows:",
            "                row_key = row.get(key_field)",
            "                payload = merged.get(str(row_key))",
            "                if not payload:",
            "                    continue",
            "                existing = row.get(merge_as)",
            "                if isinstance(existing, dict):",
            "                    updated = dict(payload)",
            "                    updated.update(existing)",
            "                    row[merge_as] = updated",
            "                elif existing in (None, '', {}):",
            "                    row[merge_as] = payload",
            "        return rows",
            "    finally:",
            "        cursor.close()",
            "        conn.close()",
            f"module = importlib.import_module({module_name!r})",
            f"callable_obj = getattr(module, {callable_name!r})",
            "rows = callable_obj()",
            "if rows is None:",
            "    rows = []",
            "elif not isinstance(rows, list):",
            "    rows = list(rows)",
            f"rows = _merge_auxiliary_rows(rows, {auxiliary_relation_hints!r}, {str(corpus_plan.row_id_field or 'product_id')!r}) if {str(corpus_plan.row_enrichment_strategy or '')!r} == 'host_python_wrapper' else rows",
            "print(json.dumps(rows, ensure_ascii=False, default=_json_default))",
        ]
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
        raise _IndexingError(
            "host python fetch failed",
            warning_codes=["host_python_fetch_failed", "row_source_fetch_failed"],
            error=(result.stderr or result.stdout or "host python fetch failed").strip(),
        )
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise _IndexingError(
            "host python fetch returned invalid json",
            warning_codes=["host_python_fetch_failed"],
            error="host python fetch returned invalid json",
        ) from exc
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
    row_id_field = str(corpus_plan.row_id_field or "product_id")
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
            new_rows: list[dict[str, Any]] = []
            for row in batch:
                row_id = row.get(row_id_field)
                if row_id is None:
                    new_rows.append(row)
                    continue
                normalized_id = str(row_id)
                if normalized_id in seen_ids:
                    continue
                seen_ids.add(normalized_id)
                new_rows.append(row)
            if not new_rows:
                break
            rows.extend(new_rows)
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
        raw_image_url = str(image_url).strip()
        resolved_image_url = urljoin(base_url, raw_image_url) if base_url else raw_image_url
        normalized.append(
            {
                **row,
                "product_id": product_id,
                "resolved_image_url": resolved_image_url,
            }
        )
    return normalized


def _run_discovery_image_seed_script(
    *,
    corpus_plan: RagCorpusPlan,
    host_context: HostExportContext | None,
    cancel_event: Event | None,
    deps: _IndexingDeps,
    reason: str,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "preseed_attempted": True,
        "preseed_reason": reason,
        "preseed_outcome": "seed_unavailable",
    }
    if _cancelled(cancel_event):
        diagnostics["preseed_outcome"] = "cancelled"
        return diagnostics
    shared_host_runtime = deps.shared_host_runtime
    if shared_host_runtime is None:
        return diagnostics
    try:
        prep_result, backend_root = shared_host_runtime.ensure_prepared(corpus_plan=corpus_plan)
    except Exception as exc:
        diagnostics["preseed_error"] = str(exc)
        return diagnostics
    seed_path_text = str(getattr(prep_result, "seed_source_path", "") or "").strip()
    python_executable = Path(str(getattr(prep_result, "python_executable", "") or "")).resolve()
    if not seed_path_text:
        return diagnostics
    seed_path = Path(seed_path_text).resolve()
    if not seed_path.exists():
        return diagnostics
    result = subprocess.run(
        [str(python_executable), str(seed_path)],
        cwd=backend_root,
        env=build_backend_subprocess_env(backend_root=backend_root),
        capture_output=True,
        text=True,
        check=False,
    )
    diagnostics["preseed_stdout"] = str(result.stdout or "").strip() or None
    diagnostics["preseed_stderr"] = str(result.stderr or "").strip() or None
    if result.returncode != 0:
        diagnostics["preseed_outcome"] = "failed"
        diagnostics["preseed_error"] = diagnostics["preseed_stderr"] or diagnostics["preseed_stdout"] or "seed failed"
        return diagnostics
    diagnostics["preseed_outcome"] = "seeded"
    return diagnostics


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
        resolved_image_url = str(image_url).strip()
        if "resolved_image_url" not in row:
            resolved_image_url = urljoin(str(row.get("__host_base_url") or "").strip(), resolved_image_url)
        normalized.append(
            {
                **row,
                "product_id": product_id,
                "resolved_image_url": resolved_image_url,
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


def _flatten_retrieval_text_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    if isinstance(value, dict):
        flattened: list[str] = []
        for item in value.values():
            flattened.extend(_flatten_retrieval_text_value(item))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_retrieval_text_value(item))
        return flattened
    return []


def _build_discovery_image_retrieval_text(row: dict[str, Any]) -> str:
    preferred_fields = (
        "product_display_name",
        "product_name",
        "name",
        "title",
        "brand",
        "brand_name",
        "manufacturer",
        "category",
        "main_category",
        "sub_category",
        "subcategory",
        "description",
        "summary",
        "details",
        "keywords",
        "tags",
        "benefits",
        "usage",
        "skin_type",
        "variant_name",
        "option_name",
        "options",
    )
    ignored_fields = {
        "product_id",
        "id",
        "image_url",
        "resolved_image_url",
        "__host_base_url",
        "site_id",
        "corpus",
    }
    fragments: list[str] = []
    seen: set[str] = set()

    def _append(value: Any) -> None:
        for token in _flatten_retrieval_text_value(value):
            normalized = token.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            fragments.append(normalized)

    for field in preferred_fields:
        _append(row.get(field))
    for key, value in row.items():
        if key in ignored_fields or key in preferred_fields:
            continue
        _append(value)
    return " ".join(fragments)


def _sanitize_auxiliary_relation_hints(hints: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for hint in hints or []:
        table_name = str(hint.get("table_name") or "").strip()
        key_field = str(hint.get("key_field") or "").strip()
        merge_as = str(hint.get("merge_as") or "").strip()
        text_fields = [str(item).strip() for item in hint.get("text_fields") or [] if str(item).strip()]
        if not (_is_safe_sql_identifier(table_name) and _is_safe_sql_identifier(key_field) and _is_safe_sql_identifier(merge_as)):
            continue
        valid_fields = [field for field in text_fields if _is_safe_sql_identifier(field)]
        if not valid_fields:
            continue
        sanitized.append(
            {
                "table_name": table_name,
                "key_field": key_field,
                "merge_as": merge_as,
                "text_fields": valid_fields,
            }
        )
    return sanitized


def _is_safe_sql_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(value or "").strip()))


def _extract_discovery_image_path_values(row: dict[str, Any], path: str) -> list[Any]:
    parts = [part for part in str(path or "").split(".") if part]
    if not parts:
        return []
    current_values: list[Any] = [row]
    for part in parts:
        next_values: list[Any] = []
        for current in current_values:
            if isinstance(current, dict) and part in current:
                next_values.append(current[part])
            elif isinstance(current, (list, tuple)):
                for item in current:
                    if isinstance(item, dict) and part in item:
                        next_values.append(item[part])
        current_values = next_values
        if not current_values:
            return []
    return current_values


def _assign_nested_payload_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path or "").split(".") if part]
    if not parts:
        return
    cursor = target
    for part in parts[:-1]:
        current = cursor.get(part)
        if not isinstance(current, dict):
            current = {}
            cursor[part] = current
        cursor = current
    cursor[parts[-1]] = value


def _build_discovery_image_sparse_text(*, row: dict[str, Any], corpus_plan: RagCorpusPlan) -> str:
    if corpus_plan.sparse_text_paths:
        fragments: list[str] = []
        seen: set[str] = set()
        for path in corpus_plan.sparse_text_paths:
            for value in _extract_discovery_image_path_values(row, path):
                for token in _flatten_retrieval_text_value(value):
                    normalized = token.strip()
                    lowered = normalized.lower()
                    if not normalized or lowered in seen:
                        continue
                    seen.add(lowered)
                    fragments.append(normalized)
        if fragments:
            return " ".join(fragments)
    return _build_discovery_image_retrieval_text(row)


def _build_discovery_image_payload(
    *,
    row: dict[str, Any],
    corpus_plan: RagCorpusPlan,
    site_id: str,
    retrieval_text: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": int(row["product_id"]),
        "image_url": str(row["resolved_image_url"]),
        "site_id": site_id,
        "corpus": "discovery_image",
        "retrieval_text": retrieval_text,
    }
    if corpus_plan.payload_paths:
        selected: dict[str, Any] = {}
        for path in corpus_plan.payload_paths:
            values = _extract_discovery_image_path_values(row, path)
            if not values:
                continue
            value = values[0] if len(values) == 1 else values
            if value in (None, "", [], {}):
                continue
            _assign_nested_payload_path(selected, path, value)
        payload.update(selected)
        return payload
    payload.update(
        {
            key: value
            for key, value in row.items()
            if key not in {"product_id", "resolved_image_url", "__host_base_url"} and value is not None
        }
    )
    return payload


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
        output = model.get_image_features(**inputs)
    if isinstance(output, torch.Tensor):
        features = output
    elif hasattr(output, "pooler_output"):
        features = output.pooler_output
    else:
        raise AttributeError("unexpected output from CLIP.get_image_features")
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


def _cancelled_result(*, corpus_plan: RagCorpusPlan | None = None) -> dict[str, Any]:
    payload = {
        "status": "aborted_by_host_failure",
        "enabled": False,
        "documents_indexed": 0,
        "warning_codes": [],
        "reason": "host_lane_failed",
        "alias_swapped": False,
        "smoke_passed": False,
    }
    if corpus_plan is not None:
        payload.update(
            {
                "collection_alias": corpus_plan.collection_alias,
                "build_collection": corpus_plan.build_collection,
                "loader_strategy": corpus_plan.loader_strategy,
            }
        )
    return payload


def _coerce_cancelled_result(
    *,
    result: dict[str, Any],
    corpus_plan: RagCorpusPlan,
    cancel_event: Event | None,
) -> dict[str, Any]:
    if not _cancelled(cancel_event):
        return result
    return _cancelled_result(corpus_plan=corpus_plan)


def _failure_result(
    *,
    corpus_plan: RagCorpusPlan,
    reason: str,
    warning_codes: list[str] | None = None,
    error: str | None = None,
    log_paths: dict[str, str] | None = None,
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
        "error": error,
        "log_paths": dict(log_paths or {}),
        "alias_swapped": False,
        "smoke_passed": False,
    }


def _skipped_result(
    *,
    corpus_plan: RagCorpusPlan,
    reason: str,
    warning_codes: list[str] | None = None,
    error: str | None = None,
    log_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "enabled": False,
        "documents_indexed": 0,
        "collection_alias": corpus_plan.collection_alias,
        "build_collection": corpus_plan.build_collection,
        "loader_strategy": corpus_plan.loader_strategy,
        "warning_codes": list(warning_codes or []),
        "reason": reason,
        "error": error,
        "log_paths": dict(log_paths or {}),
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


def _with_optional_diagnostics(result: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    for key, value in diagnostics.items():
        if value is None:
            continue
        result[key] = value
    return result
