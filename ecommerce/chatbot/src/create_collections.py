
import os
import sys
from typing import Dict, Any, List
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models

# Load environment variables
load_dotenv()

# Configuration
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")  # Default to localhost if not set
VECTOR_SIZE = 1536  # OpenAI text-embedding-3-small dimension


def get_qdrant_client() -> QdrantClient:
    """Returns a QdrantClient instance."""
    if not QDRANT_API_KEY and "localhost" not in QDRANT_URL:
        print("Warning: QDRANT_API_KEY is not set.")
    
    return QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
    )


def create_collections():
    """Creates the necessary Qdrant collections with configured schemas."""
    client = get_qdrant_client()
    
    collections_config: Dict[str, Dict[str, Any]] = {
        "fashion_products": {
            "vectors_config": models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            ),
            "sparse_vectors_config": {
                "text-sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            },
            "indexes": [
                {"field_name": "gender", "schema": "keyword"},
                {"field_name": "masterCategory", "schema": "keyword"},
                {"field_name": "subCategory", "schema": "keyword"},
                {"field_name": "articleType", "schema": "keyword"},
                {"field_name": "baseColour", "schema": "keyword"},
                {"field_name": "season", "schema": "keyword"},
                {"field_name": "year", "schema": "integer"},
                {"field_name": "usage", "schema": "keyword"},
            ]
        },
        "musinsa_faq": {
            "vectors_config": models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            ),
            "sparse_vectors_config": {
                "text-sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            },
            "indexes": [
                {"field_name": "main_category", "schema": "keyword"},
                {"field_name": "sub_category", "schema": "keyword"},
            ]
        },
        "ecommerce_terms": {
            "vectors_config": models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            ),
            "sparse_vectors_config": {
                "text-sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            },
            "indexes": [
                {"field_name": "clause_title", "schema": "text"},
                {"field_name": "category", "schema": "keyword"},
            ]
        }
    }

    existing_collections = {c.name for c in client.get_collections().collections}

    for name, config in collections_config.items():
        if name in existing_collections:
            print(f"Collection '{name}' already exists. Skipping creation.")
            # Note: In a real migration scenario, we might want to update config or recreate.
            # For now, we assume if it exists, it's fine.
            continue
        
        print(f"Creating collection '{name}'...")
        try:
            client.create_collection(
                collection_name=name,
                vectors_config=config["vectors_config"],
                sparse_vectors_config=config.get("sparse_vectors_config")
            )
            print(f"Successfully created collection '{name}'.")
            
            # Create payload indexes
            print(f"Creating indexes for '{name}'...")
            for idx in config["indexes"]:
                field_name = idx["field_name"]
                schema_type = idx["schema"]
                
                # Qdrant client payload index creation
                # Note: create_payload_index is async in some versions/contexts, 
                # but synchronous client methods usually wait.
                client.create_payload_index(
                    collection_name=name,
                    field_name=field_name,
                    field_schema=models.TextIndexParams(
                        type="text",
                        tokenizer=models.TokenizerType.WORD,
                        min_token_len=2,
                        max_token_len=20,
                        lowercase=True
                    ) if schema_type == "text" else schema_type
                )
                print(f"  - Created index for field '{field_name}' ({schema_type})")
                
        except Exception as e:
            print(f"Error creating collection '{name}': {e}")

if __name__ == "__main__":
    create_collections()
