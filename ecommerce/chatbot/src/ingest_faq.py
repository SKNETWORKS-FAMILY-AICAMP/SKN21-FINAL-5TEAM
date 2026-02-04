
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
    
    # Path pattern
    # Assuming only one json file exists or picking the latest
    pattern = "ecommerce/chatbot/data/raw/musinsa_faq/musinsa_faq_*.json"
    files = glob.glob(pattern)
    if not files:
        print("No FAQ file found.")
        return
    
    filepath = sorted(files)[-1] # Take latest
    print(f"Reading {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    print(f"Loaded {len(data)} records.")
    
    client = get_qdrant_client()
    openai = get_openai_client()
    
    batch_size = 50 
    
    for i in tqdm(range(0, len(data), batch_size), desc="Ingesting Batches"):
        batch = data[i:i+batch_size]
        
        texts_to_embed = [item['question'] for item in batch]
        
        try:
            resp = openai.embeddings.create(
                input=texts_to_embed,
                model=settings.EMBEDDING_MODEL
            )
            embeddings = [d.embedding for d in resp.data]
            
            points = []
            for j, item in enumerate(batch):
                # FAQ doesn't have ID, generate UUID
                point_id = str(uuid.uuid4())
                
                payload = {
                    "main_category": item.get("main_category"),
                    "sub_category": item.get("sub_category"),
                    "question": item.get("question"),
                    "answer": item.get("answer")
                }
                
                points.append(models.PointStruct(
                    id=point_id,
                    vector=embeddings[j],
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
