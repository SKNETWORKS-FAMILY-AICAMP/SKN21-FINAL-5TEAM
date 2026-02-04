
from typing import List
from langchain_core.messages import HumanMessage, SystemMessage
from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

def retrieve(state: AgentState):
    """
    Retrieve documents from Qdrant.
    For the skeleton, we currently default to searching the 'fashion_products' collection.
    TODO: Implement routing logic to choose between multiple collections.
    """
    print("---RETRIEVE---")
    question = state["question"]
    client = get_qdrant_client()
    openai = get_openai_client()

    # Embed the question
    # Note: In a real app, use a proper embedding function. 
    # Here we assume OpenAI embedding for simplicity of the skeleton.
    emb_response = openai.embeddings.create(
        input=question,
        model=settings.EMBEDDING_MODEL
    )
    query_vector = emb_response.data[0].embedding

    # Search (Defaulting to fashion_products for now)
    # TODO: Make retrieval modular/routed
    # Search (Defaulting to fashion_products for now)
    # Using query_points as search is deprecated/missing in this version
    search_result = client.query_points(
        collection_name=settings.COLLECTION_FASHION,
        query=query_vector,
        limit=5
    ).points
    
    # Format documents
    documents = []
    for hit in search_result:
        # Assuming payload has 'productDisplayName' or similar. 
        # We'll dump the whole payload for now.
        content = f"Item: {hit.payload}" 
        documents.append(content)

    return {"documents": documents}

def generate(state: AgentState):
    """
    Generate answer using OpenAI.
    """
    print("---GENERATE---")
    question = state["question"]
    documents = state["documents"]
    openai = get_openai_client()

    context = "\n\n".join(documents)
    
    system_prompt = """You are a helpful assistant for an ecommerce platform. 
    Use the following context to answer the user's question. 
    If the answer is not in the context, say you don't know."""
    
    user_message = f"Context:\n{context}\n\nQuestion: {question}"

    response = openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        temperature=0
    )
    
    return {"generation": response.choices[0].message.content}
