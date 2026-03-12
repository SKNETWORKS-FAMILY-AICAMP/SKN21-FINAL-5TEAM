
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
import uvicorn
import json
import uuid

# Import all models to ensure SQLAlchemy mappers are properly initialized
# This prevents "failed to locate a name" errors with circular relationships
try:
    import ecommerce.backend.app.router.users.models
    import ecommerce.backend.app.router.shipping.models
    import ecommerce.backend.app.router.orders.models
    import ecommerce.backend.app.router.products.models
    import ecommerce.backend.app.router.carts.models
    import ecommerce.backend.app.router.payments.models
    import ecommerce.backend.app.router.points.models
    import ecommerce.backend.app.router.reviews.models
    import ecommerce.backend.app.router.user_history.models
except ImportError:
    pass # Ignore if some modules are not found/needed

# LangChain / LangGraph imports
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage, BaseMessage
from ecommerce.chatbot.src.graph.workflow import graph_app

app = FastAPI(title="Chatbot Evaluation Adapter")

# OpenAI-compatible Request Models
class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    function_call: Optional[Dict[str, Any]] = None

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    temperature: Optional[float] = 0.7

    class Config:
        extra = "allow"  # Allow extra fields like 'max_tokens', etc.

# OpenAI-compatible Response Models
class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int = 1234567890
    model: str
    choices: List[Choice]
    
class ModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int = 1234567890
    owned_by: str = "inhouse"

class ModelListResponse(BaseModel):
    object: str = "list"
    data: List[ModelCard]

DEFAULT_USER_ID = 1

def convert_messages(messages: List[ChatMessage]) -> List[BaseMessage]:
    """Convert OpenAI messages to LangChain messages"""
    lc_messages = []
    for msg in messages:
        if msg.role == "user":
            lc_messages.append(HumanMessage(content=msg.content or ""))
        elif msg.role == "assistant":
            # 툴 호출이 포함된 경우 처리
            additional_kwargs = {}
            tool_calls = []
            if msg.tool_calls:
                lc_tool_calls = []
                for tc in msg.tool_calls:
                    lc_tool_calls.append({
                        "id": tc.get("id", str(uuid.uuid4())),
                        "type": "function",
                        "function": tc.get("function", {})
                    })
                additional_kwargs["tool_calls"] = lc_tool_calls
                tool_calls = lc_tool_calls # For AIMessage constructor in newer langchain versions
            
            lc_messages.append(AIMessage(
                content=msg.content or "",
                tool_calls=tool_calls,
                additional_kwargs=additional_kwargs
            ))
        elif msg.role == "tool":
            # Tool response
            # Note: OpenAI sends tool role, LangChain expects ToolMessage
            tool_call_id = msg.tool_call_id if hasattr(msg, "tool_call_id") else "unknown"
            lc_messages.append(ToolMessage(
                content=msg.content or "",
                tool_call_id=tool_call_id
            ))
        elif msg.role == "system":
            lc_messages.append(SystemMessage(content=msg.content or ""))
            
    return lc_messages

@app.get("/v1/models", response_model=ModelListResponse)
async def list_models():
    """Return a dummy list of models to satisfy OpenAI client"""
    return ModelListResponse(
        data=[
            ModelCard(id="inhouse"),
            ModelCard(id="my-ecommerce-bot")
        ]
    )

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    try:
        # 1. Convert messages
        history = convert_messages(request.messages)
        
        # 2. Prepare initial state
        # 벤치마크는 보통 user_id 등을 별도로 주지 않으므로 기본값 사용
        initial_state = {
            "messages": history,
            "user_info": {"id": DEFAULT_USER_ID, "name": "Test User"}, 
            "current_task": None, # Reset task context
            "is_evaluation": True
        }
        
        # 3. Invoke Graph (Safe Mode)
        # Use astream to capture intermediate outputs. 
        # If tool execution fails (e.g. missing mock), we can still return the generated tool call.
        messages = []
        try:
            async for state in graph_app.astream(initial_state, stream_mode="values"):
                if "messages" in state:
                    messages = state["messages"]
                    # If we detect a tool call, we update our candidate message.
                    # We continue the loop to allow 'smart_validation' to improve the tool call if applicable.
                    # If 'tool_node' crashes next, we catch the exception and use the latest 'messages'.
        except Exception as e:
            print(f"Workflow execution interrupted: {e}")
            # Fallback: Proceed with whatever messages we captured so far.
        
        result_state = {"messages": messages}
        
        # 4. Extract target message (Prioritize message with tool_calls for benchmark)
        # 벤치마크는 Tool Call 자체를 평가하므로, 최종 답변보다 Tool Call이 포함된 메시지를 우선 반환
        messages = result_state["messages"]
        last_message = messages[-1]
        
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                last_message = msg
                break
        
        # 5. Convert to OpenAI Response
        tool_calls = []
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            for tc in last_message.tool_calls:
                tool_calls.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"]
                    }
                })
        
        finish_reason = "stop"
        if tool_calls:
            finish_reason = "tool_calls"
            
        choice = Choice(
            index=0,
            message=ChoiceMessage(
                content=str(last_message.content) if last_message.content else None,
                tool_calls=tool_calls if tool_calls else None
            ),
            finish_reason=finish_reason
        )
        
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            model=request.model,
            choices=[choice]
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)
