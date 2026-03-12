
import json
import uuid
from tqdm import tqdm
from qdrant_client.http import models
from ecommerce.backend.app.infrastructure.qdrant import get_qdrant_client
from ecommerce.backend.app.core.config import settings
from ecommerce.backend.data_preprocessing.bge_m3_embedding import (
    embed_texts,
    get_embedding_dim,
)
import os


def ensure_faq_collection(client, embedding_dim: int):
    collection_name = settings.COLLECTION_FAQ

    try:
        if client.collection_exists(collection_name):
            return
    except Exception:
        # Fallback for older client/server compatibility
        try:
            client.get_collection(collection_name=collection_name)
            return
        except Exception:
            pass

    print(f"Collection '{collection_name}' not found. Creating...")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=embedding_dim,
            distance=models.Distance.COSINE,
        ),
        sparse_vectors_config={
            "text-sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=False)
            )
        },
    )

    client.create_payload_index(
        collection_name=collection_name,
        field_name="main_category",
        field_schema="keyword",
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="sub_category",
        field_schema="keyword",
    )

    print(f"Collection '{collection_name}' created.")

def ingest_faq():
    print("--- Starting Musinsa FAQ Ingestion ---")
    
    # Path to preprocessed final FAQ data (relative to project root)
    filepath = "ecommerce/backend/data/raw/musinsa_faq/musinsa_faq_20260203_162139_final.json"
    
    if not os.path.exists(filepath):
        print(f"Error: Final FAQ file not found at {filepath}")
        return
    
    print(f"Reading {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    print(f"Loaded {len(data)} records.")
    
    # Initialize sparse model (dense is handled by local BGE-M3 helper)
    from fastembed import SparseTextEmbedding

    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    embedding_dim = get_embedding_dim()

    client = get_qdrant_client()
    ensure_faq_collection(client, embedding_dim)
    
    batch_size = 50 
    
    for i in tqdm(range(0, len(data), batch_size), desc="Ingesting Batches"):
        batch = data[i:i+batch_size]
        
        # Use vector_input for embeddings (contains both question and answer context)
        texts_to_embed = [item['vector_input'] for item in batch]
        
        try:
            # 1. Dense Embeddings (BGE-M3)
            dense_vectors = embed_texts(texts_to_embed)
            
            # 2. Sparse Embeddings
            sparse_vectors = list(sparse_model.embed(texts_to_embed))

            points = []
            for j, item in enumerate(batch):
                # Reuse existing ID and Payload from the preprocessed file
                point_id = item.get("id", str(uuid.uuid4()))
                payload = item.get("payload", {})
                
                # Check for existing dense vector in file (optional optimization)
                # But here we regenerate for consistency with sparse
                
                sparse_vec = models.SparseVector(
                    indices=sparse_vectors[j].indices.tolist(),
                    values=sparse_vectors[j].values.tolist()
                )

                points.append(models.PointStruct(
                    id=point_id,
                    vector={
                        "": dense_vectors[j],
                        "text-sparse": sparse_vec
                    },
                    payload=payload
                ))
            
            client.upsert(
                collection_name=settings.COLLECTION_FAQ,
                points=points
            )
            
        except Exception as e:
            print(f"Error in batch {i}: {e}")
            continue

    print("--- FAQ Ingestion Completed ---")

if __name__ == "__main__":
    ingest_faq()
