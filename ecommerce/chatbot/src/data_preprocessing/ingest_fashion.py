import pandas as pd
from tqdm import tqdm
from qdrant_client.http import models
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings


def ingest_fashion():
    print("--- Starting Fashion Dataset Ingestion ---")

    # paths
    csv_path = (
        "ecommerce/chatbot/data/processed/fashion-1000-balanced/sampled_styles.csv"
    )

    # Load Data
    print(f"Reading {csv_path}...")
    # on_bad_lines='skip' handles potential malformed lines
    df = pd.read_csv(csv_path, on_bad_lines="skip")

    # Drop rows with missing productDisplayName as it's our primary text
    df = df.dropna(subset=["productDisplayName"])

    # Debug: Sample
    print(f"Loaded {len(df)} records.")

    # Processing
    client = get_qdrant_client()
    openai = get_openai_client()

    # Init Sparse Embedder
    try:
        from fastembed import SparseTextEmbedding

        sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        print("Sparse retrieval model loaded.")
    except Exception as e:
        print(f"Failed to load sparse model: {e}")
        return

    # Check if collection exists and has correct config, else recreate
    try:
        client.get_collection(collection_name=settings.COLLECTION_FASHION)
        print(
            f"Collection {settings.COLLECTION_FASHION} exists. Recreating it to ensure correct vector config..."
        )
        client.delete_collection(collection_name=settings.COLLECTION_FASHION)
    except Exception:
        pass

    client.create_collection(
        collection_name=settings.COLLECTION_FASHION,
        vectors_config={
            "": models.VectorParams(
                size=settings.EMBEDDING_DIM, distance=models.Distance.COSINE
            )
        },
        sparse_vectors_config={"text-sparse": models.SparseVectorParams()},
    )
    print("Collection configured for Hybrid Search.")

    batch_size = 100
    points = []

    total_records = len(df)

    for i in tqdm(range(0, total_records, batch_size), desc="Ingesting Batches"):
        batch = df.iloc[i : i + batch_size]

        # Build richer textual representation for better semantic matching
        texts = []
        for _, row in batch.iterrows():
            text = f"{row['productDisplayName']}. Category: {row['masterCategory']} > {row['subCategory']} > {row['articleType']}. Color: {row['baseColour']}. Season: {row['season']}. Usage: {row['usage']}."
            texts.append(text)

        try:
            # Dense Embeddings
            resp = openai.embeddings.create(input=texts, model=settings.EMBEDDING_MODEL)
            dense_vectors = [d.embedding for d in resp.data]

            # Sparse Embeddings
            sparse_embeddings = list(sparse_model.embed(texts))

            # Prepare points
            batch_points = []
            for j, (index, row) in enumerate(batch.iterrows()):
                # Construct Payload
                payload = {
                    "id": int(row["id"]),
                    "gender": row["gender"],
                    "masterCategory": row["masterCategory"],
                    "subCategory": row["subCategory"],
                    "articleType": row["articleType"],
                    "baseColour": row["baseColour"],
                    "season": row["season"],
                    "year": int(row["year"]) if pd.notna(row["year"]) else None,
                    "usage": row["usage"],
                    "productDisplayName": row["productDisplayName"],
                    "search_text": texts[j],
                }

                point_id = int(row["id"])

                # Named vectors format for hybrid search
                vector_dict = {
                    "": dense_vectors[j],  # Default is unnamed for dense
                    "text-sparse": models.SparseVector(
                        indices=sparse_embeddings[j].indices.tolist(),
                        values=sparse_embeddings[j].values.tolist(),
                    ),
                }

                batch_points.append(
                    models.PointStruct(id=point_id, vector=vector_dict, payload=payload)
                )

            # Upsert
            client.upsert(
                collection_name=settings.COLLECTION_FASHION, points=batch_points
            )

        except Exception as e:
            print(f"Error processing batch {i}: {e}")
            continue

    print("--- Fashion Ingestion Completed ---")


if __name__ == "__main__":
    ingest_fashion()
