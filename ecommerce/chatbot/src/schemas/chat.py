
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Unique session identifier for conversation history")
    message: str = Field(..., description="User's query")
    model_config = ConfigDict(extra="forbid")

class SourceDocument(BaseModel):
    content: str
    metadata: dict

class ChatResponse(BaseModel):
    answer: str
    source_documents: Optional[List[SourceDocument]] = None
