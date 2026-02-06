
from typing import List
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.schemas.nlu import NLUResult
from ecommerce.chatbot.src.infrastructure.qdrant import get_qdrant_client
from ecommerce.chatbot.src.infrastructure.openai import get_openai_client
from ecommerce.chatbot.src.core.config import settings

@traceable(run_type="retriever", name="Retrieve Documents")
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

@traceable(run_type="llm", name="Generate Answer")
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

def mock_nlu(user_message: str) -> NLUResult:
    """
    Mock NLU function to simulate checking intent and slots.
    Replace this with actual NLU logic or service call.
    """
    # Logic for demonstration:
    # If message contains specific keywords, return simulated results.
    if "배송" in user_message:
        return NLUResult(intent="check_delivery", slots={"category": "delivery"})
    elif "1234" in user_message:
        return NLUResult(intent=None, slots={"order_id": "1234"})
    
    return NLUResult(intent=None, slots={})

def update_state_node(state: AgentState) -> dict:
    """
    Updates the agent state based on the NLU result from the latest user message.

    This node implements the following logic:
    1. Intent Preservation: If NLU detects a new intent, update it. 
       If NLU returns None (no new intent), preserve the existing `current_intent`.
    2. Slot Merging: Merge new slots into the existing `order_slots` dictionary 
       instead of replacing it.

    Args:
        state (AgentState): The current state of the agent.

    Returns:
        dict: A dictionary containing the updates to the state.
    """
    print("---UPDATE STATE---")
    
    messages = state.get("messages", [])
    if not messages:
        return {}

    # 1. Extract NLU Output from the last user message
    last_message = messages[-1]
    nlu_result = mock_nlu(last_message.content)

    print(f"DEBUG: NLU Result: {nlu_result}")

    updates = {}

    # 2. Intent Preservation Logic
    # - If NLU detects an intent (not None), update the state.
    # - If NLU intent is None, do NOT include 'current_intent' in return (implies keeping old).
    if nlu_result.intent is not None:
        updates["current_intent"] = nlu_result.intent
    else:
        # Explicitly preserving logic comment:
        # state["current_intent"] remains unchanged.
        pass

    # 3. Slot Merging Logic
    # - Start with existing slots (or empty dict if None)
    # - Update with new slots from NLU
    current_slots = state.get("order_slots") or {}
    # Create a new dictionary to ensure immutability/clean update
    merged_slots = current_slots.copy()
    merged_slots.update(nlu_result.slots)
    
    updates["order_slots"] = merged_slots

    return updates
