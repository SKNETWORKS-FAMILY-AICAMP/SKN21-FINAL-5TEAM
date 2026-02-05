import os
import json
import uuid
from tqdm import tqdm
from qdrant_client.http import models
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

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
    
    client = get_qdrant_client()
    openai = get_openai_client()
    batch_size = 50
    
    for i in tqdm(range(0, len(data), batch_size), desc="Ingesting Batches"):
        batch = data[i:i+batch_size]
        
        # Use 'text' field for embeddings (already preprocessed)
        texts_to_embed = [item['text'] for item in batch]
        
        try:
            resp = openai.embeddings.create(
                input=texts_to_embed,
                model=settings.EMBEDDING_MODEL
            )
            embeddings = [d.embedding for d in resp.data]
            
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
                
                points.append(models.PointStruct(
                    id=point_id,
                    vector=embeddings[j],
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
