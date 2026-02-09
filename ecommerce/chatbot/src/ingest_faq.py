
import json
import uuid
from tqdm import tqdm
from qdrant_client.http import models
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings
import glob
import os

def ingest_faq():
    print("--- Starting Musinsa FAQ Ingestion ---")
    
    # Path to preprocessed final FAQ data (relative to project root)
    filepath = "ecommerce/chatbot/data/raw/musinsa_faq/musinsa_faq_20260203_162139_final.json"
    
    if not os.path.exists(filepath):
        print(f"Error: Final FAQ file not found at {filepath}")
        return
    
    print(f"Reading {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    print(f"Loaded {len(data)} records.")
    
    # Initialize FastEmbed
    from fastembed import SparseTextEmbedding
    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

    client = get_qdrant_client()
    openai = get_openai_client()
    
    batch_size = 50 
    
    for i in tqdm(range(0, len(data), batch_size), desc="Ingesting Batches"):
        batch = data[i:i+batch_size]
        
        # Use vector_input for embeddings (contains both question and answer context)
        texts_to_embed = [item['vector_input'] for item in batch]
        
        try:
            # 1. Dense Embeddings
            resp = openai.embeddings.create(
                input=texts_to_embed,
                model=settings.EMBEDDING_MODEL
            )
            dense_vectors = [d.embedding for d in resp.data]
            
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
