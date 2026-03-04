import os
import json
import uuid
from tqdm import tqdm
from qdrant_client.http import models
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.data_preprocessing.bge_m3_embedding import (
    embed_texts,
    get_embedding_dim,
)


def ensure_terms_collection(client, embedding_dim: int):
    collection_name = settings.COLLECTION_TERMS

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
        field_name="clause_title",
        field_schema=models.TextIndexParams(
            type="text",
            tokenizer=models.TokenizerType.WORD,
            min_token_len=2,
            max_token_len=20,
            lowercase=True,
        ),
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="category",
        field_schema="keyword",
    )

    print(f"Collection '{collection_name}' created.")

def ingest_terms():
    print("--- Starting Ecommerce Terms Ingestion ---")
    
    # Path to preprocessed final terms data (relative to project root)
    filepath = "ecommerce/chatbot/data/raw/ecommerce_standard/ecommerce_standard_preprocessed.json"
    
    if not os.path.exists(filepath):
        print(f"Error: Terms file not found at {filepath}")
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
    ensure_terms_collection(client, embedding_dim)
    batch_size = 50
    
    for i in tqdm(range(0, len(data), batch_size), desc="Ingesting Batches"):
        batch = data[i:i+batch_size]
        
        # Use 'text' field for embeddings (already preprocessed)
        texts_to_embed = [item['text'] for item in batch]
        
        try:
            # 1. Dense Embeddings (BGE-M3)
            dense_vectors = embed_texts(texts_to_embed)

            # 2. Sparse Embeddings (FastEmbed BM25)
            sparse_vectors = list(sparse_model.embed(texts_to_embed))
            
            points = []
            for j, item in enumerate(batch):
                point_id = str(uuid.uuid4())
                
                # Metadata and original text for the user
                payload = {
                    "text": item.get("text"),
                    **item.get("metadata", {})
                }
                
                # Compatibility field for existing search logic if it uses clause_title
                if "title" in payload and "clause_title" not in payload:
                    payload["clause_title"] = payload["title"]
                
                # Create Sparse Vector dict for Qdrant
                # fastembed returns numpy, convert to list
                sparse_vec = models.SparseVector(
                    indices=sparse_vectors[j].indices.tolist(),
                    values=sparse_vectors[j].values.tolist()
                )

                points.append(models.PointStruct(
                    id=point_id,
                    vector={
                        "": dense_vectors[j],           # Default dense vector
                        "text-sparse": sparse_vec       # Sparse vector
                    },
                    payload=payload
                ))
            
            client.upsert(
                collection_name=settings.COLLECTION_TERMS,
                points=points
            )
            
        except Exception as e:
            print(f"Error in batch {i}: {e}")
            continue

    print("--- Terms Ingestion Completed ---")

if __name__ == "__main__":
    ingest_terms()
