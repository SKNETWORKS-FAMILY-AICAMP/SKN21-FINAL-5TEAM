"""지식 검색(Retrieval) 도구: Hybrid Search + Reranking"""

import os
from pathlib import Path

from langchain_core.tools import tool
from qdrant_client import models
from fastembed import SparseTextEmbedding
from flashrank import Ranker, RerankRequest

from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.data_preprocessing.bge_m3_embedding import embed_texts

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
            print(
                f"Warning: Failed to load reranker (cache_dir={cache_dir or 'default'}): {e}"
            )

    RANKER = None


def ensure_retrieval_models():
    # 모듈 import 시 실패했더라도 호출 시 재시도
    _init_sparse_model()
    _init_ranker()


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
        "주문/결제": "구매/결제",
    }
    mapped = cat_map.get(category, category)

    return models.Filter(
        must=[models.FieldCondition(key=field, match=models.MatchValue(value=mapped))]
    )


def _extract_text(payload: dict) -> str:
    """페이로드에서 텍스트 추출"""
    if payload.get("question"):
        return f"{payload['question']} {payload.get('answer', '')}".strip()
    return (
        payload.get("text") or payload.get("content") or payload.get("title", "")
    ).strip()


def _merge_sibling_texts(siblings) -> str:
    """형제 청크들의 텍스트를 병합 (공통 접두사 중복 제거)"""
    if not siblings:
        return ""
    texts = [_extract_text(p.payload) for p in siblings]
    if len(texts) == 1:
        return texts[0]

    # 1. 공통 접두사 찾기
    prefix = texts[0]
    for t in texts[1:]:
        i = 0
        while i < len(prefix) and i < len(t) and prefix[i] == t[i]:
            i += 1
        prefix = prefix[:i]

    # 2. 구조적 제목이라고 판단될 경우 (7자 이상 또는 ] 포함) 중복 제거 병합
    if prefix:
        prefix_len = len(prefix)
        if prefix_len > 7 or ("]" in prefix):
            # 제목을 상단에 배치
            cleaned_texts = [prefix.rstrip()]
            for t in texts:
                remainder = t[prefix_len:].lstrip()
                if remainder:
                    # 내용마다 불렛포인트를 추가하여 구조화
                    cleaned_texts.append("- " + remainder)
            return "\n".join(cleaned_texts)

    # 3. 조건이 맞지 않으면 그냥 줄바꿈으로 연결하여 반환 (Fallback)
    return "\n".join(texts)


@tool
def search_knowledge_base(query: str, category: str = None) -> dict:
    """
    쇼핑몰 규정, 배송 정책, 교환/반품 안내 등 지식 베이스를 검색합니다.
    주문 상태나 배송 현황 조회가 아니라, '규정'이나 '정보'를 물어볼 때 사용합니다.

    Args:
        query: 검색할 질문 내용
        category: 카테고리 (배송, 취소/반품/교환, 주문/결제, 회원 정보, 상품/AS 문의, 약관)
    """
    ensure_retrieval_models()

    # 임베딩 생성
    try:
        dense = embed_texts([query])[0]

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
                        models.Prefetch(
                            query=dense, using="", filter=query_filter, limit=20
                        ),
                        models.Prefetch(
                            query=models.SparseVector(
                                indices=sparse_idx, values=sparse_val
                            ),
                            using="text-sparse",
                            filter=query_filter,
                            limit=20,
                        ),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=20,
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

    # 중복 제거 및 단일 문서 추출
    unique = list({c.id: c for c in candidates}.values())

    # Parent Document Retrieval & Contextual Merging
    faq_passages = []
    terms_to_expand = set()

    for c in unique:
        if c.payload and "article_no" in c.payload:
            article_no = c.payload.get("article_no")
            paragraph = c.payload.get("paragraph", "")
            terms_to_expand.add((article_no, paragraph))
        else:
            faq_passages.append(
                {
                    "id": str(c.id),
                    "text": _extract_text(c.payload),
                    "meta": c.payload,
                    "score": float(getattr(c, "score", 0.0)),
                }
            )

    expanded_passages = []
    for article_no, paragraph in terms_to_expand:
        must_conditions = [
            models.FieldCondition(
                key="article_no", match=models.MatchValue(value=article_no)
            ),
            models.FieldCondition(
                key="paragraph", match=models.MatchValue(value=paragraph)
            ),
        ]

        try:
            scroll_res, _ = client.scroll(
                collection_name=settings.COLLECTION_TERMS,
                scroll_filter=models.Filter(must=must_conditions),
                limit=100,
            )
            if scroll_res:

                def sub_point_key(p):
                    sp = p.payload.get("sub_point", "")
                    return int(sp) if sp.isdigit() else 0

                sorted_siblings = sorted(scroll_res, key=sub_point_key)

                # 공통 접두사를 활용하여 중복 텍스트를 제거하고 병합
                merged_text = _merge_sibling_texts(sorted_siblings)

                rep = sorted_siblings[0]
                passages_id = f"merged_{article_no}_{paragraph}"

                max_score = max(
                    [
                        float(getattr(c, "score", 0.0))
                        for c in unique
                        if c.payload
                        and c.payload.get("article_no") == article_no
                        and c.payload.get("paragraph", "") == paragraph
                    ],
                    default=0.0,
                )

                expanded_passages.append(
                    {
                        "id": passages_id,
                        "text": merged_text,
                        "meta": rep.payload,
                        "score": max_score,
                    }
                )
        except Exception as e:
            print(f"Error expanding terms {article_no}-{paragraph}: {e}")

    passages = faq_passages + expanded_passages

    if RANKER:
        reranked = RANKER.rerank(RerankRequest(query=query, passages=passages))[:5]
        selected = [
            {"text": item["text"], "meta": item.get("meta", {})} for item in reranked
        ]
    else:
        # Reranker 실패 시 점수 기반 fallback
        sorted_passages = sorted(passages, key=lambda x: x["score"], reverse=True)
        selected = [{"text": p["text"], "meta": p["meta"]} for p in sorted_passages[:5]]

    # 결과 포맷팅
    documents = []
    for res in selected:
        meta = res.get("meta", {})
        doc_type = (
            "FAQ"
            if "main_category" in meta
            else "약관"
            if "category" in meta
            else "정보"
        )
        documents.append(f"[{doc_type}] {res['text']}")

    return {"documents": documents, "count": len(documents)}
