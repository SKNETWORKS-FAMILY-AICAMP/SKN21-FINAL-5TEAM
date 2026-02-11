"""
지식 검색(Retrieval) 관련 Tools.
(Hybrid Search + Reranking)
"""

from langchain_core.tools import tool
from qdrant_client import models
from fastembed import SparseTextEmbedding
from flashrank import Ranker, RerankRequest

from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

# Initialize retrieval models globally (Load once)
# Note: In a production environment with multiple workers, 
# this might need to be handled differently (e.g., separate service).
print("Loading Retrieval Models (Tool)...")
try:
    SPARSE_MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
    # FlashRank is lightweight (ONNX) but better cached
    RANKER = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank_cache")
    print("Retrieval Models (Tool) Loaded.")
except Exception as e:
    print(f"Warning: Failed to load retrieval models: {e}")
    SPARSE_MODEL = None
    RANKER = None


@tool
def search_knowledge_base(query: str, category: str = None) -> dict:
    """
    쇼핑몰 규정, 배송 정책, 교환/반품 안내 등 지식 베이스를 검색합니다.
    주문 상태나 배송 현황 조회가 아니라, '규정'이나 '정보'를 물어볼 때 사용합니다.
    
    Args:
        query: 검색할 질문 내용
        category: 카테고리 (배송, 취소/반품/교환, 주문/결제, 회원 정보, 상품/AS 문의, 약관) - 선택 사항
        
    Returns:
        검색된 문서 목록 및 관련성 여부
    """
    if not SPARSE_MODEL or not RANKER:
        return {"error": "Retrieval models are not initialized."}

    client = get_qdrant_client()
    openai = get_openai_client()
    
    # 1. 질문 임베딩 생성 (Dense & Sparse)
    try:
        # Dense
        emb_response = openai.embeddings.create(
            input=query,
            model=settings.EMBEDDING_MODEL
        )
        query_dense_vector = emb_response.data[0].embedding
        
        # Sparse
        query_sparse_vector = list(SPARSE_MODEL.embed([query]))[0]
        query_sparse_indices = query_sparse_vector.indices.tolist()
        query_sparse_values = query_sparse_vector.values.tolist()
    except Exception as e:
        return {"error": f"임베딩 생성 실패: {str(e)}"}

    # 2. 검색 전략 실행 (Hybrid Search)
    collections = [settings.COLLECTION_FAQ, settings.COLLECTION_TERMS]
    candidates = []

    for col in collections:
        # 필터 설정
        query_filter = None
        if category:
            if col == settings.COLLECTION_FAQ:
                field_name = "main_category"
                mapped_category = "취소/교환/반품" if category == "취소/반품/교환" else category
            else: # COLLECTION_TERMS
                field_name = "category"
                if category == "회원 정보": mapped_category = "회원"
                elif category == "주문/결제": mapped_category = "구매/결제"
                else: mapped_category = category
            
            query_filter = models.Filter(
                must=[models.FieldCondition(key=field_name, match=models.MatchValue(value=mapped_category))]
            )

        try:
            prefetch = [
                models.Prefetch(
                    query=query_dense_vector,
                    using="", # Default dense vector
                    filter=query_filter,
                    limit=20,
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=query_sparse_indices, values=query_sparse_values),
                    using="text-sparse",
                    filter=query_filter,
                    limit=20,
                ),
            ]
            
            results = client.query_points(
                collection_name=col,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF), # Reciprocal Rank Fusion
                limit=20, # Fetch top 20 candidates for reranking
            ).points
            
            for hit in results:
                # Add collection context to payload for reranker/LLM
                hit.payload["_collection"] = col
                candidates.append(hit)
                
        except Exception as e:
            print(f"Error searching {col}: {e}")

    # 3. Reranking using FlashRank
    if not candidates:
        return {"documents": [], "message": "관련된 정보를 찾을 수 없습니다."}
        
    # Deduplicate candidates by ID
    unique_candidates = {c.id: c for c in candidates}.values()
    
    passages = []
    for c in unique_candidates:
        # Construct text for reranker
        text_content = (
            c.payload.get('question', '') + " " + c.payload.get('answer', '') if c.payload.get('question') else
            c.payload.get('text', '') or 
            c.payload.get('content', '') or 
            c.payload.get('title', '')
        ).strip()
        
        passages.append({
            "id": c.id,
            "text": text_content,
            "meta": c.payload
        })
        
    rerank_request = RerankRequest(query=query, passages=passages)
    reranked_results = RANKER.rerank(rerank_request)
    
    # 4. Top 5 Selection
    top_results = reranked_results[:5]
    
    documents = []
    for res in top_results:
        payload = res["meta"]
        doc_type = "정보"
        if 'main_category' in payload: doc_type = "FAQ"
        elif 'category' in payload: doc_type = "약관"
        
        content_text = res["text"]
        documents.append(f"[{doc_type}] {content_text}")

    return {
        "documents": documents,
        "count": len(documents)
    }
