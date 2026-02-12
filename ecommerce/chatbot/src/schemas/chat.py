from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any

class ChatRequest(BaseModel):
    message: str = Field(..., description="User's query")
    user_id: str = Field("guest", description="User identifier")
    # 이전 대화 상태 (메시지 이력 포함)
    previous_state: Optional[Dict[str, Any]] = Field(None, description="Full conversation state for stateless processing")
    model_config = ConfigDict(extra="ignore")

class ChatResponse(BaseModel):
    answer: Optional[str] = None
    action_status: Optional[str] = None
    action_name: Optional[str] = None
    order_id: Optional[str] = None
    ui_action: Optional[str] = Field(None, description="UI action type (e.g., 'show_order_list')")
    ui_data: Optional[List[Dict[str, Any]]] = Field(None, description="UI rendering data (e.g., order list)")
    state: Dict[str, Any] = Field(..., description="Updated conversation state to be passed back in next request")
