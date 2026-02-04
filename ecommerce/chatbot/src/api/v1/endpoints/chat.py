
from fastapi import APIRouter, HTTPException
from ecommerce.chatbot.src.schemas.chat import ChatRequest, ChatResponse
from ecommerce.chatbot.src.graph.workflow import graph_app

router = APIRouter()

@router.post("/", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Chat endpoint that invokes the LangGraph workflow.
    """
    inputs = {"question": request.message, "messages": []}
    
    try:
        # Invoke the graph
        # Since graph_app.invoke is synchronous (unless we use ainvoke), 
        # we run it directly here. For production, consider `await graph_app.ainvoke`.
        result = await graph_app.ainvoke(inputs)
        
        answer = result.get("generation", "Sorry, something went wrong.")
        documents = [] # Retrieve docs from result if needed for SourceDocument mapping
        
        return ChatResponse(
            answer=answer,
            source_documents=None # Populate if we want to return sources
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
