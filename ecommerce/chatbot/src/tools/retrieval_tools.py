"""지식 검색(Retrieval) 도구: Hybrid Search + Reranking"""

from langchain_core.tools import tool
from qdrant_client import models
from fastembed import SparseTextEmbedding
from flashrank import Ranker, RerankRequest

from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

# 모델 초기화 (전역, 1회만 로드)
print("Loading Retrieval Models...")
try:
    SPARSE_MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
    RANKER = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank_cache")
    print("Retrieval Models Loaded.")
except Exception as e:
    print(f"Warning: Failed to load retrieval models: {e}")
    SPARSE_MODEL = RANKER = None

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
    if not SPARSE_MODEL or not RANKER:
        return {"error": "Retrieval models are not initialized."}

    # 임베딩 생성
    try:
        dense = get_openai_client().embeddings.create(
            input=query, model=settings.EMBEDDING_MODEL
        ).data[0].embedding
        
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
            
            candidates.extend(results)
        except Exception as e:
            print(f"Error searching {col}: {e}")

    if not candidates:
        return {"documents": [], "message": "관련된 정보를 찾을 수 없습니다."}

    # 중복 제거 + Reranking
    unique = {c.id: c for c in candidates}.values()
    passages = [{"id": c.id, "text": _extract_text(c.payload), "meta": c.payload} for c in unique]
    
    reranked = RANKER.rerank(RerankRequest(query=query, passages=passages))[:5]
    
    # 결과 포맷팅
    documents = []
    for res in reranked:
        doc_type = "FAQ" if 'main_category' in res["meta"] else "약관" if 'category' in res["meta"] else "정보"
        documents.append(f"[{doc_type}] {res['text']}")

    return {"documents": documents, "count": len(documents)}
