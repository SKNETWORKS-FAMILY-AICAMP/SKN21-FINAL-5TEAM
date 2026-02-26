"""지식 검색(Retrieval) 도구: Hybrid Search + Reranking"""

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
        print("Sparse retrieval model loaded.")
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
        configured_cache,
        str(Path.home() / ".cache" / "flashrank"),
        "/tmp/flashrank_cache",
        None,
    ]

    for cache_dir in cache_candidates:
        try:
            kwargs = {"model_name": model_name}
            if cache_dir:
                kwargs["cache_dir"] = cache_dir
            RANKER = Ranker(**kwargs)
            print(f"Reranker loaded. cache_dir={cache_dir or 'default'}")
            return
        except Exception as e:
            print(f"Warning: Failed to load reranker (cache_dir={cache_dir or 'default'}): {e}")

    RANKER = None


def _ensure_retrieval_models():
    # 모듈 import 시 실패했더라도 호출 시 재시도
    _init_sparse_model()
    _init_ranker()


print("Loading Retrieval Models...")
_ensure_retrieval_models()
if SPARSE_MODEL is not None and RANKER is not None:
    print("Retrieval Models Loaded.")
else:
    print("Warning: Retrieval models are partially/fully unavailable.")

def _build_filter(category: str, collection: str):
    """카테고리 필터 생성"""
    if not category:
        return None
    
    is_faq = collection == settings.COLLECTION_FAQ
    field = "main_category" if is_faq else "category"
    
    # 카테고리 매핑
    cat_map = {
        "취소/반품/교환": "취소/교환/반품",
        "회원 정보": "회원",
        "주문/결제": "구매/결제"
    }
    mapped = cat_map.get(category, category)
    
    return models.Filter(
        must=[models.FieldCondition(key=field, match=models.MatchValue(value=mapped))]
    )

def _extract_text(payload: dict) -> str:
    """페이로드에서 텍스트 추출"""
    if payload.get('question'):
        return f"{payload['question']} {payload.get('answer', '')}".strip()
    return (payload.get('text') or payload.get('content') or payload.get('title', '')).strip()

@tool
def search_knowledge_base(query: str, category: str = None) -> dict:
    """
    쇼핑몰 규정, 배송 정책, 교환/반품 안내 등 지식 베이스를 검색합니다.
    주문 상태나 배송 현황 조회가 아니라, '규정'이나 '정보'를 물어볼 때 사용합니다.
    
    Args:
        query: 검색할 질문 내용
        category: 카테고리 (배송, 취소/반품/교환, 주문/결제, 회원 정보, 상품/AS 문의, 약관)
    """
    _ensure_retrieval_models()

    # 임베딩 생성
    try:
        dense = get_openai_client().embeddings.create(
            input=query, model=settings.EMBEDDING_MODEL
        ).data[0].embedding
        
        sparse_idx = None
        sparse_val = None
        if SPARSE_MODEL:
            sparse = list(SPARSE_MODEL.embed([query]))[0]
            sparse_idx = sparse.indices.tolist()
            sparse_val = sparse.values.tolist()
    except Exception as e:
        return {"error": f"임베딩 생성 실패: {str(e)}"}

    # Hybrid 검색 (FAQ + 약관)
    client = get_qdrant_client()
    candidates = []
    
    for col in [settings.COLLECTION_FAQ, settings.COLLECTION_TERMS]:
        query_filter = _build_filter(category, col)
        
        try:
            if sparse_idx is not None and sparse_val is not None:
                results = client.query_points(
                    collection_name=col,
                    prefetch=[
                        models.Prefetch(query=dense, using="", filter=query_filter, limit=20),
                        models.Prefetch(
                            query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                            using="text-sparse", filter=query_filter, limit=20
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=20
                ).points
            else:
                # Sparse 모델 실패 시 Dense-only fallback
                results = client.query_points(
                    collection_name=col,
                    query=dense,
                    using="",
                    filter=query_filter,
                    limit=20,
                ).points
            
            candidates.extend(results)
        except Exception as e:
            print(f"Error searching {col}: {e}")

    if not candidates:
        return {"documents": [], "message": "관련된 정보를 찾을 수 없습니다."}

    # 중복 제거 + Reranking
    unique = {c.id: c for c in candidates}.values()
    passages = [{"id": c.id, "text": _extract_text(c.payload), "meta": c.payload} for c in unique]
    
    if RANKER:
        reranked = RANKER.rerank(RerankRequest(query=query, passages=passages))[:5]
        selected = [
            {"text": item["text"], "meta": item.get("meta", {})}
            for item in reranked
        ]
    else:
        # Reranker 실패 시 점수 기반 fallback
        sorted_unique = sorted(unique, key=lambda x: float(getattr(x, "score", 0.0)), reverse=True)
        selected = [
            {"text": _extract_text(c.payload), "meta": c.payload}
            for c in sorted_unique[:5]
        ]
    
    # 결과 포맷팅
    documents = []
    for res in selected:
        meta = res.get("meta", {})
        doc_type = "FAQ" if 'main_category' in meta else "약관" if 'category' in meta else "정보"
        documents.append(f"[{doc_type}] {res['text']}")

    return {"documents": documents, "count": len(documents)}
