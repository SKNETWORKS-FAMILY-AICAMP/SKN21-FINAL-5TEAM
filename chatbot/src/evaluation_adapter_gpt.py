import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass
import uvicorn
import json
import uuid
import time

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
    pass

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage, BaseMessage
from chatbot.src.graph.workflow import graph_app

app = FastAPI(title="Chatbot Evaluation Adapter")


class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    function_call: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    temperature: Optional[float] = 0.7

    class Config:
        extra = "allow"


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


@dataclass
class ToolCallBuildResult:
    tool_calls: List[Dict[str, Any]]
    finish_reason: str
    debug: Dict[str, Any]


def _safe_get(d: Any, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _first_non_empty(*values):
    for v in values:
        if v is not None and v != "":
            return v
    return None


def _compact_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _json_dumps(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def convert_messages(messages: List[ChatMessage]) -> List[BaseMessage]:
    lc_messages: List[BaseMessage] = []

    for msg in messages:
        if msg.role == "user":
            lc_messages.append(HumanMessage(content=msg.content or ""))

        elif msg.role == "assistant":
            additional_kwargs = {}
            tool_calls = []

            if msg.tool_calls:
                lc_tool_calls = []
                for tc in msg.tool_calls:
                    lc_tool_calls.append({
                        "id": tc.get("id", str(uuid.uuid4())),
                        "type": tc.get("type", "function"),
                        "function": tc.get("function", {})
                    })
                additional_kwargs["tool_calls"] = lc_tool_calls
                tool_calls = lc_tool_calls

            lc_messages.append(
                AIMessage(
                    content=msg.content or "",
                    tool_calls=tool_calls,
                    additional_kwargs=additional_kwargs
                )
            )

        elif msg.role == "tool":
            tool_call_id = getattr(msg, "tool_call_id", "unknown")
            lc_messages.append(
                ToolMessage(
                    content=msg.content or "",
                    tool_call_id=tool_call_id
                )
            )

        elif msg.role == "system":
            lc_messages.append(SystemMessage(content=msg.content or ""))

    return lc_messages


def _normalize_existing_tool_call(tc: Any) -> Optional[Dict[str, Any]]:
    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
    tc_name = None
    tc_args = None

    if isinstance(tc, dict):
        if "name" in tc:
            tc_name = tc.get("name")
            tc_args = tc.get("args", {})
        elif "function" in tc:
            fn = tc.get("function", {}) or {}
            tc_name = fn.get("name")
            raw_arguments = fn.get("arguments", {})
            if isinstance(raw_arguments, str):
                try:
                    tc_args = json.loads(raw_arguments)
                except Exception:
                    tc_args = raw_arguments
            else:
                tc_args = raw_arguments
    else:
        tc_name = getattr(tc, "name", None)
        tc_args = getattr(tc, "args", {})

    if not tc_name:
        return None

    return {
        "id": tc_id or f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {
            "name": tc_name,
            "arguments": _json_dumps(tc_args) if isinstance(tc_args, dict) else str(tc_args)
        }
    }


def _infer_tool_name_from_request(request: ChatCompletionRequest) -> Optional[str]:
    tc = request.tool_choice

    if isinstance(tc, dict):
        fn_name = _safe_get(tc, "function", "name")
        if fn_name:
            return fn_name

    if isinstance(tc, str):
        if tc not in {"none", "auto", "required"}:
            return tc

    if request.tools and len(request.tools) == 1:
        only_tool = request.tools[0]
        fn_name = _safe_get(only_tool, "function", "name")
        if fn_name:
            return fn_name

    return None


def _find_action_candidates(state: Dict[str, Any]) -> Dict[str, Any]:
    outputs = _safe_get(state, "outputs", default={}) or {}
    input_payload = _safe_get(state, "inputs", "input", default={}) or {}

    state_resume = _safe_get(state, "resume", default={}) or {}
    outputs_resume = _safe_get(outputs, "resume", default={}) or {}
    input_resume = _safe_get(input_payload, "resume", default={}) or {}

    state_order_context = _safe_get(state, "order_context", default={}) or {}
    outputs_order_context = _safe_get(outputs, "order_context", default={}) or {}

    state_user_info = _safe_get(state, "user_info", default={}) or {}
    outputs_user_info = _safe_get(outputs, "user_info", default={}) or {}

    action = _first_non_empty(
        state_resume.get("action"),
        outputs_resume.get("action"),
        input_resume.get("action"),
        state_order_context.get("last_tool"),
        outputs_order_context.get("last_tool"),
        state_order_context.get("pending_action"),
        outputs_order_context.get("pending_action"),
        _safe_get(state, "action"),
        _safe_get(outputs, "action"),
    )

    order_id = _first_non_empty(
        state_resume.get("selected_order_id"),
        outputs_resume.get("selected_order_id"),
        input_resume.get("selected_order_id"),
        _safe_get(state, "selected_order_id"),
        _safe_get(outputs, "selected_order_id"),
        state_order_context.get("selected_order_id"),
        outputs_order_context.get("selected_order_id"),
    )

    user_id = _first_non_empty(
        state_user_info.get("id"),
        outputs_user_info.get("id"),
        _safe_get(state, "user_id"),
        _safe_get(outputs, "user_id"),
        DEFAULT_USER_ID,
    )

    reason = _first_non_empty(
        state_resume.get("reason"),
        outputs_resume.get("reason"),
        input_resume.get("reason"),
        state_resume.get("refund_reason"),
        outputs_resume.get("refund_reason"),
        state_resume.get("cancel_reason"),
        outputs_resume.get("cancel_reason"),
        state_resume.get("exchange_reason"),
        outputs_resume.get("exchange_reason"),
    )

    new_option = _first_non_empty(
        state_resume.get("new_option"),
        outputs_resume.get("new_option"),
        state_resume.get("requested_option"),
        outputs_resume.get("requested_option"),
    )

    payment_method = _first_non_empty(
        state_resume.get("payment_method"),
        outputs_resume.get("payment_method"),
        state_resume.get("new_payment_method"),
        outputs_resume.get("new_payment_method"),
    )

    review_text = _first_non_empty(
        state_resume.get("review_text"),
        outputs_resume.get("review_text"),
        state_resume.get("content"),
        outputs_resume.get("content"),
        state_resume.get("review_content"),
        outputs_resume.get("review_content"),
    )

    rating = _first_non_empty(
        state_resume.get("rating"),
        outputs_resume.get("rating"),
        state_resume.get("review_rating"),
        outputs_resume.get("review_rating"),
    )

    gift_card_number = _first_non_empty(
        state_resume.get("gift_card_number"),
        outputs_resume.get("gift_card_number"),
        state_resume.get("gift_code"),
        outputs_resume.get("gift_code"),
    )

    query = _first_non_empty(
        state_resume.get("query"),
        outputs_resume.get("query"),
        _safe_get(state, "user_query"),
        _safe_get(outputs, "user_query"),
    )

    address = _first_non_empty(
        state_resume.get("address"),
        outputs_resume.get("address"),
        state_resume.get("shipping_address"),
        outputs_resume.get("shipping_address"),
        state_resume.get("selected_address"),
        outputs_resume.get("selected_address"),
    )

    return {
        "action": action,
        "order_id": order_id,
        "user_id": user_id,
        "reason": reason,
        "new_option": new_option,
        "payment_method": payment_method,
        "review_text": review_text,
        "rating": rating,
        "gift_card_number": gift_card_number,
        "query": query,
        "address": address,
        "resume_sources": {
            "state_resume": state_resume,
            "outputs_resume": outputs_resume,
            "input_resume": input_resume,
        },
        "order_context_sources": {
            "state_order_context": state_order_context,
            "outputs_order_context": outputs_order_context,
        },
        "user_info_sources": {
            "state_user_info": state_user_info,
            "outputs_user_info": outputs_user_info,
        },
    }


def build_tool_calls_from_state(state: Dict[str, Any], request: ChatCompletionRequest) -> ToolCallBuildResult:
    found = _find_action_candidates(state)
    action = found["action"]

    debug = {
        "action": action,
        "order_id": found["order_id"],
        "user_id": found["user_id"],
        "resume_sources": found["resume_sources"],
        "order_context_sources": found["order_context_sources"],
        "user_info_sources": found["user_info_sources"],
    }

    tool_name = action

    if not tool_name:
        debug["tool_name_missing"] = True
        return ToolCallBuildResult(tool_calls=[], finish_reason="stop", debug=debug)

    order_id = found["order_id"]
    user_id = found["user_id"]
    reason = found["reason"]
    new_option = found["new_option"]
    payment_method = found["payment_method"]
    review_text = found["review_text"]
    rating = found["rating"]
    gift_card_number = found["gift_card_number"]
    query = found["query"]
    address = found["address"]

    args: Dict[str, Any] = {}

    if tool_name in {"order_detail", "shipping"}:
        args = {"order_id": order_id, "user_id": user_id}

    elif tool_name == "cancel":
        args = {
            "order_id": order_id,
            "user_id": user_id,
            "reason": reason or "단순 변심",
        }

    elif tool_name == "refund":
        args = {
            "order_id": order_id,
            "user_id": user_id,
            "reason": reason or "단순 변심",
        }

    elif tool_name == "exchange":
        args = {
            "order_id": order_id,
            "user_id": user_id,
            "reason": reason or "사이즈 교환",
            "new_option": new_option,
        }

    elif tool_name == "payment_change":
        args = {
            "order_id": order_id,
            "user_id": user_id,
            "payment_method": payment_method,
        }

    elif tool_name == "option_change":
        args = {
            "order_id": order_id,
            "user_id": user_id,
            "new_option": new_option,
        }

    elif tool_name == "review_list":
        args = {"user_id": user_id, "order_id": order_id}

    elif tool_name == "review_create":
        args = {
            "user_id": user_id,
            "order_id": order_id,
            "content": review_text,
            "rating": rating,
        }

    elif tool_name == "gift_card":
        args = {
            "user_id": user_id,
            "gift_card_number": gift_card_number,
        }

    elif tool_name == "knowledge":
        args = {"query": query}

    elif tool_name == "address_search":
        args = {}

    elif tool_name == "address_save":
        args = {
            "user_id": user_id,
            "address": address,
        }

    args = _compact_dict(args)

    required_order_id_tools = {
        "order_detail",
        "shipping",
        "cancel",
        "refund",
        "exchange",
        "payment_change",
        "option_change",
    }

    if tool_name in required_order_id_tools and not args.get("order_id"):
        debug["missing_required"] = ["order_id"]
        return ToolCallBuildResult(tool_calls=[], finish_reason="stop", debug=debug)

    tool_calls = [
        {
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": _json_dumps(args),
            }
        }
    ]

    debug["mapped_tool_name"] = tool_name
    debug["built_args"] = args

    return ToolCallBuildResult(
        tool_calls=tool_calls,
        finish_reason="tool_calls",
        debug=debug
    )


@app.get("/v1/models", response_model=ModelListResponse)
async def list_models():
    return ModelListResponse(
        data=[
            ModelCard(id="inhouse"),
            ModelCard(id="my-ecommerce-bot")
        ]
    )


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    try:
        history = convert_messages(request.messages)

        initial_state = {
            "messages": history,
            "user_info": {"id": DEFAULT_USER_ID, "name": "Test User"},
            "current_task": None,
            "is_evaluation": True
        }

        messages = history
        final_state = initial_state
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}

        try:
            async for state in graph_app.astream(initial_state, config=config, stream_mode="values"):
                final_state = state
                if "messages" in state and state["messages"]:
                    messages = state["messages"]
        except Exception as e:
            print(f"Workflow execution interrupted: {e}")

        if not messages:
            messages = history

        last_message: BaseMessage = messages[-1] if messages else AIMessage(content="에러가 발생했습니다.")

        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_message = msg
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    break

        tool_calls: List[Dict[str, Any]] = []
        finish_reason = "stop"

        if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls") and last_message.tool_calls:
            for tc in last_message.tool_calls:
                normalized = _normalize_existing_tool_call(tc)
                if normalized and _safe_get(normalized, "function", "name"):
                    tool_calls.append(normalized)

            if tool_calls:
                finish_reason = "tool_calls"

        if not tool_calls:
            built = build_tool_calls_from_state(final_state, request)
            tool_calls = built.tool_calls
            finish_reason = built.finish_reason
            print("[EVAL DEBUG]", json.dumps(built.debug, ensure_ascii=False))

        response_content = None if tool_calls else (str(last_message.content) if getattr(last_message, "content", None) else None)

        choice = Choice(
            index=0,
            message=ChoiceMessage(
                content=response_content,
                tool_calls=tool_calls if tool_calls else None
            ),
            finish_reason=finish_reason
        )

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            created=int(time.time()),
            model=request.model,
            choices=[choice]
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)