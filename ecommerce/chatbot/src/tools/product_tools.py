"""상품 검색(Product Search) 도구: Hybrid Search + Reranking"""

import os
from pathlib import Path

from langchain_core.tools import tool
from qdrant_client import models
from fastembed import SparseTextEmbedding
from flashrank import Ranker, RerankRequest

from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

SPARSE_MODEL = None
RANKER = None


def _init_sparse_model():
    global SPARSE_MODEL
    if SPARSE_MODEL is not None:
        return

    try:
        SPARSE_MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
    except Exception as e:
        print(f"Warning: Failed to load sparse retrieval model: {e}")
        SPARSE_MODEL = None


def _init_ranker():
    global RANKER
    if RANKER is not None:
        return

    model_name = "ms-marco-MiniLM-L-12-v2"
    configured_cache = os.getenv("FLASHRANK_CACHE_DIR")
    cache_candidates = [
        str(Path.home() / ".cache" / "flashrank"),
        configured_cache,
        "/tmp/flashrank_cache",
        None,
    ]

    for cache_dir in cache_candidates:
        try:
            kwargs = {"model_name": model_name}
            if cache_dir:
                kwargs["cache_dir"] = cache_dir
            RANKER = Ranker(**kwargs)
            print(f"Reranker loaded successfully. cache_dir={cache_dir or 'default'}")
            return
        except Exception as e:
            print(
                f"Warning: Failed to load reranker with cache_dir={cache_dir or 'default'}: {e}"
            )
            pass
    RANKER = None


def ensure_retrieval_models():
    _init_sparse_model()
    _init_ranker()


@tool
def search_products_vector(query: str, limit: int = 5) -> dict:
    """
    고객이 상품(옷, 패션 아이템 등)을 검색하거나 추천받고 싶어할 때,
    유사한 상품 목록을 Hybrid Vector Search를 통해 찾아옵니다.

    Args:
        query: 검색할 상품의 구체적인 특징, 색상, 카테고리 등 자연어 질의 (예: "여름에 입을 시원한 파란색 반팔티")
        limit: 검색할 상품 개수 (기본 5개)
    """
    ensure_retrieval_models()

    try:
        dense = (
            get_openai_client()
            .embeddings.create(input=query, model=settings.EMBEDDING_MODEL)
            .data[0]
            .embedding
        )

        sparse_idx = None
        sparse_val = None
        if SPARSE_MODEL:
            sparse = list(SPARSE_MODEL.embed([query]))[0]
            sparse_idx = sparse.indices.tolist()
            sparse_val = sparse.values.tolist()
    except Exception as e:
        return {"error": f"상품 검색 실패 (임베딩 에러): {str(e)}"}

    client = get_qdrant_client()
    candidates = []

    try:
        if sparse_idx is not None and sparse_val is not None:
            results = client.query_points(
                collection_name=settings.COLLECTION_FASHION,
                prefetch=[
                    models.Prefetch(query=dense, using="", limit=20),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_idx, values=sparse_val
                        ),
                        using="text-sparse",
                        limit=20,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=20,
            ).points
        else:
            # Fallback to Dense-only
            results = client.query_points(
                collection_name=settings.COLLECTION_FASHION,
                query=dense,
                using="",
                limit=20,
            ).points

        candidates.extend(results)
    except Exception as e:
        return {"error": f"상품 검색 실패 (Qdrant 검색 에러): {str(e)}"}

    if not candidates:
        return {
            "message": "조건에 맞는 상품을 찾지 못했습니다.",
            "ui_template": "product_list",
            "ui_data": [],
        }

    # Reranking with FlashRank
    if RANKER:
        try:
            passages = [
                {
                    "id": str(c.id),
                    "text": c.payload.get(
                        "search_text", c.payload.get("productDisplayName", "")
                    ),
                    "meta": c.payload,
                }
                for c in candidates
            ]
            rerank_request = RerankRequest(query=query, passages=passages)
            rerank_results = RANKER.rerank(rerank_request)

            top_k_ids = [res["id"] for res in rerank_results[:limit]]
            # Preserve reranker order
            candidates_by_id = {str(c.id): c for c in candidates}
            final_candidates = [
                candidates_by_id[i] for i in top_k_ids if i in candidates_by_id
            ]
        except Exception as e:
            print(f"Reranking fallback due to error: {e}")
            # Fallback if reranking fails
            final_candidates = candidates[:limit]
    else:
        final_candidates = candidates[:limit]

    # 포맷팅하여 UI Data 생성
    ui_products = []
    for c in final_candidates:
        payload = c.payload or {}
        ui_products.append(
            {
                "id": payload.get("id"),
                "name": payload.get("productDisplayName", "Unknown Product"),
                "price": 30000,  # Mock price because price isn't in styles.csv metadata
                "category": payload.get("subCategory", ""),
                "color": payload.get("baseColour", ""),
                "season": payload.get("season", ""),
            }
        )

    return {
        "message": f"찾아본 상품 {len(ui_products)}개 목록입니다.",
        "ui_template": "product_list",
        "ui_data": ui_products,
        "requires_selection": False,
    }
