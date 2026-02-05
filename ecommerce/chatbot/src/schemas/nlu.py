from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class NLUResult(BaseModel):
    """
    Result from Natural Language Understanding (NLU) process.
    """
    intent: Optional[str] = Field(None, description="Detected intent of the user. None if no new intent detected.")
    slots: Dict[str, Any] = Field(default_factory=dict, description="Extracted slots from the user message.")
