
import pandas as pd
from tqdm import tqdm
from qdrant_client.http import models
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

def ingest_fashion():
    print("--- Starting Fashion Dataset Ingestion ---")
    
    # paths
    csv_path = "ecommerce/chatbot/data/raw/fashion-dataset/styles.csv"
    
    # Load Data
    print(f"Reading {csv_path}...")
    # on_bad_lines='skip' handles potential malformed lines
    df = pd.read_csv(csv_path, on_bad_lines='skip')
    
    # Drop rows with missing productDisplayName as it's our primary text
    df = df.dropna(subset=['productDisplayName'])
    
    # Debug: Sample
    print(f"Loaded {len(df)} records.")
    
    # Processing
    client = get_qdrant_client()
    openai = get_openai_client()
    
    batch_size = 100
    points = []
    
    # Iterate with tqdm
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        text_to_embed = str(row['productDisplayName'])
        
        # We process in batches to be efficient with OpenAI API calls if needed, 
        # but for simplicity/robustness we might embed one by one or batch embed.
        # Let's batch embed for speed.
        
        # Actually, let's collect text first then batch embed.
        pass

    # Batch Processing
    total_records = len(df)
    
    for i in tqdm(range(0, total_records, batch_size), desc="Ingesting Batches"):
        batch = df.iloc[i:i+batch_size]
        
        texts = batch['productDisplayName'].astype(str).tolist()
        
        try:
            # Embed batch
            resp = openai.embeddings.create(
                input=texts,
                model=settings.EMBEDDING_MODEL
            )
            embeddings = [d.embedding for d in resp.data]
            
            # Prepare points
            batch_points = []
            for j, (index, row) in enumerate(batch.iterrows()):
                
                # Construct Payload
                payload = {
                    "id": row['id'],
                    "gender": row['gender'],
                    "masterCategory": row['masterCategory'],
                    "subCategory": row['subCategory'],
                    "articleType": row['articleType'],
                    "baseColour": row['baseColour'],
                    "season": row['season'],
                    "year": int(row['year']) if pd.notna(row['year']) else None,
                    "usage": row['usage'],
                    "productDisplayName": row['productDisplayName']
                }
                
                # Check IDs. Qdrant needs int or uuid. 'id' in csv seems to be integer-like.
                # using row['id'] directly
                point_id = int(row['id'])
                
                batch_points.append(models.PointStruct(
                    id=point_id,
                    vector=embeddings[j],
                    payload=payload
                ))
            
            # Upsert
            client.upsert(
                collection_name=settings.COLLECTION_FASHION,
                points=batch_points
            )
            
        except Exception as e:
            print(f"Error processing batch {i}: {e}")
            # Continue to next batch instead of crashing
            continue

    print("--- Fashion Ingestion Completed ---")

if __name__ == "__main__":
    ingest_fashion()
