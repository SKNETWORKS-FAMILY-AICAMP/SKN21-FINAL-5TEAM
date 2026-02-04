
import json
import uuid
from tqdm import tqdm
from qdrant_client.http import models
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

def ingest_terms():
    print("--- Starting Ecommerce Terms Ingestion ---")
    
    filepath = "ecommerce/chatbot/data/raw/ecommerce_standard/ecommerce_standard.json"
    print(f"Reading {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # Data is a list of dicts, but the structure might be quirky (key-value pairs)
    # Based on previous `view_file`:
    # [ {"전자상거래...": "표준약관..."}, ... ]
    
    # We need to flatten this into meaningful chunks.
    # Actually, let's inspect the data structure more carefully if needed.
    # Assuming it's a list of single-key dicts or similar.
    
    processed_items = []
    
    for item in data:
        # Since structure might be [{"Title": "Content"}, ...], let's iterate keys
        for key, value in item.items():
            processed_items.append({
                "clause_title": key,
                "content": value
            })
            
    print(f"Processed {len(processed_items)} clauses.")
    
    client = get_qdrant_client()
    openai = get_openai_client()
    batch_size = 50
    
    for i in tqdm(range(0, len(processed_items), batch_size), desc="Ingesting Batches"):
        batch = processed_items[i:i+batch_size]
        
        # Embed the Content (or Title + Content)
        # Usually searching for content context
        texts_to_embed = [f"{item['clause_title']}: {item['content']}" for item in batch]
        
        try:
            resp = openai.embeddings.create(
                input=texts_to_embed,
                model=settings.EMBEDDING_MODEL
            )
            embeddings = [d.embedding for d in resp.data]
            
            points = []
            for j, item in enumerate(batch):
                point_id = str(uuid.uuid4())
                
                payload = {
                    "clause_title": item['clause_title'],
                    "content": item['content']
                }
                
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
