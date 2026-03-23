from pathlib import Path
import os
import sys

# 프로젝트 루트 경로 설정
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
import uvicorn
import json
import uuid

# 모델 초기화 (필요 시)
try:
    import ecommerce.backend.app.router.users.models
    # ... 나머지 모델들 생략 (기존 코드 유지)
except ImportError:
    pass

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage, BaseMessage
from chatbot.src.graph.workflow import graph_app
from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.router.orders.crud import get_order_by_order_number
from chatbot.src.graph.nodes.guardrail import load_guardrail_model

app = FastAPI(title="Chatbot Evaluation Adapter")

# --- OpenAI 호환 모델 정의 ---
class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    use_guardrail: bool = False  # 가드레일 제어 옵션 추가
    use_recovery: bool = False   # 하드코딩된 의도 매핑(복구) 사용 여부
    # 벤치마크 툴에 따라 추가 필드가 올 수 있으므로 허용
    model_config = {"extra": "allow"}

class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    classification_source: Optional[str] = "Rule"

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

class ModelListResponse(BaseModel):
    data: List[ModelCard]

DEFAULT_USER_ID = 1

def convert_messages(messages: List[ChatMessage]) -> List[BaseMessage]:
    lc_messages = []
    for msg in messages:
        if msg.role == "user":
            lc_messages.append(HumanMessage(content=msg.content or ""))
        elif msg.role == "assistant":
            lc_messages.append(AIMessage(content=msg.content or "", tool_calls=msg.tool_calls or []))
        elif msg.role == "system":
            lc_messages.append(SystemMessage(content=msg.content or ""))
    return lc_messages

def normalize_korean_text(text: str) -> str:
    text = (text or "").strip().lower()

    # 자주 나오는 띄어쓰기/표현 정규화
    replacements = {
        "주문 번호": "주문번호",
        "송장 번호": "송장번호",
        "운송장 번호": "운송장번호",
        "배송 조회": "배송조회",
        "택배 조회": "택배조회",
        "주문 내역": "주문내역",
        "구매 내역": "구매내역",
        "주문 목록": "주문목록",
        "구매 목록": "구매목록",
        "사이즈 변경": "사이즈변경",
        "색상 변경": "색상변경",
        "옵션 변경": "옵션변경",
        "주문 취소": "주문취소",
        "결제 취소": "결제취소",
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    # 공백 제거 버전도 같이 활용 가능하게 반환 전 생성
    compact_text = text.replace(" ", "")
    return compact_text

@app.get("/v1/models")
async def list_models():
    return {"data": [{"id": "inhouse"}]}

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    try:
        # 1. 메시지 변환
        history = convert_messages(request.messages)
        
        # 2. 사용자 정보 및 LLM 설정 (벤치마크 지침 기반)
        # 기본값 설정
        resolved_user_id = DEFAULT_USER_ID
        
        # 벤치마크 혹은 외부에서 요청받은 모델명을 챗봇 엔진에 주입
        llm_model = request.model if request.model != "inhouse" else "gpt-4o-mini"
        
        # 모델명 정규화 (윈도우 호환을 위해 명시된 이름을 실제 태그로 변환)
        if llm_model == "qwen3_0.6b":
            llm_model = "qwen3:0.6b"
        
        # Qwen 모델이거나 경로 형태의 모델명인 경우 자동으로 vllm으로 설정
        llm_provider = getattr(request, "provider", None) 
        if not llm_provider:
            if "qwen" in llm_model.lower() or "/" in llm_model:
                llm_provider = "vllm"
            else:
                llm_provider = "openai"
        
        # 가드레일 모델 로드 (요청 시)
        if request.use_guardrail:
            load_guardrail_model()

        # 2. 초기 상태 결정
        # 시스템 메시지에서 실제 user_id 추출 (모든 모델 공통)
        # 1.5 추가: 사용자 질문에서 주문 번호가 감지되면 DB 조회하여 실제 user_id 확보 (404 예방)
        import re
        user_text = history[-1].content if history else ""
        order_match = re.search(r"ORD-[A-Za-z0-9_-]+", user_text)
        if order_match:
            order_id_raw = order_match.group(0).strip()
            try:
                db = SessionLocal()
                db_order = get_order_by_order_number(db, order_id_raw)
                if db_order:
                    resolved_user_id = db_order.user_id
                    print(f"  [Auto-Auth] Order {order_id_raw} belongs to User {resolved_user_id}. Using it for evaluation.")
                db.close()
            except Exception:
                pass

        # 요청 로그 (모든 모델 공통)
        print(f"\n[REQUEST] User: {user_text} (Target LLM: {llm_model})", flush=True)

        initial_state = {
            "messages": history,
            "pending_tasks": [],
            "completed_tasks": [],
            "current_active_task": None,
            "order_context": {
                "order_id": None,
                "target_order_id": None,
                "pending_action": None,
                "action_status": None
            },
            "search_context": {},
            "agent_results": {},
            "ui_action_required": None,
            "user_info": {"id": resolved_user_id},
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "use_guardrail": request.use_guardrail,
            "is_direct_routing": True,  # 평가 모드: order_intent_router 직행
        }

        messages = history
        final_state = initial_state
        captured_intent = None
        captured_tool = None
        captured_source = "Rule"  # 기본값
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        
        try:
            # stream_mode="updates"를 사용하여 노드별 실행 결과를 캡처합니다.
            async for chunk in graph_app.astream(initial_state, config=config, stream_mode="updates"):
                if not isinstance(chunk, dict):
                    continue

                for node_name, state_update in chunk.items():
                    print(f"[DEBUG] Node Executed: {node_name}", flush=True)

                    if isinstance(state_update, dict):
                        # 1) state merge
                        for key, val in state_update.items():
                            if key == "messages":
                                continue

                            if isinstance(val, dict) and isinstance(final_state.get(key), dict):
                                merged = dict(final_state[key])
                                merged.update(val)
                                final_state[key] = merged
                            else:
                                final_state[key] = val

                        # 2) merged order_context 기준으로 capture
                        ctx = final_state.get("order_context", {})
                        if isinstance(ctx, dict):
                            p_action = ctx.get("pending_action")
                            if p_action and not captured_intent:
                                captured_intent = p_action
                                print(f"  [DEBUG] Captured Intent: {captured_intent}", flush=True)

                            l_tool = ctx.get("last_tool")
                            if l_tool and not captured_tool:
                                captured_tool = l_tool
                                print(f"  [DEBUG] Captured Tool: {captured_tool}", flush=True)

                            source = ctx.get("classification_source")
                            if source:
                                captured_source = source

                        # 3) messages append
                        new_msgs = state_update.get("messages")
                        if new_msgs:
                            if isinstance(new_msgs, list):
                                messages.extend(new_msgs)
                            else:
                                messages.append(new_msgs)

                    else:
                        print(f"  [DEBUG] Non-dict update from {node_name}: {type(state_update)}")

        except Exception as e:
            print(f"[ERROR] Workflow execution error: {e}")
            import traceback
            traceback.print_exc()

        # 4. 마지막 메시지 추출
        last_message = messages[-1] if messages else AIMessage(content="No response")
        
        # 5. Tool Call 변환 로직 (구축 개선)
        # 최종 상태와 실시간 캡처된 의도를 종합하여 결정합니다.
        tool_calls = []
        order_ctx = final_state.get("order_context", {}) or {}
        
        # 우선순위: 1.실제실행도구(캡처) 2.분석된의도(캡처) 3.최종상태도구 4.최종상태의도
        engine_decision = (
            captured_intent
            or order_ctx.get("pending_action")
            or captured_tool
            or order_ctx.get("last_tool")
        )
        
        # 벤치마크 툴 이름 매핑 (엔진 내부 이름 -> 벤치마크 기대 이름)
        benchmark_tool_mapping = {
            "list_orders": "get_user_orders",
        }
        
        # 매핑 테이블에 없으면 엔진의 결정을 그대로 사용
        mapped_name = benchmark_tool_mapping.get(engine_decision, engine_decision) if engine_decision else None
        
        if mapped_name:
            print(f"[LOG] Engine Decision Detected: {engine_decision} -> {mapped_name}")
            
            # 인자(Arguments) 구성
            clean_args = {}
            
            # 1. 주문 번호(order_id) 추출 및 검증
            order_id = order_ctx.get("order_id") or order_ctx.get("target_order_id")
            
            # 2. user_id 해결 (DB 조회 로직 등은 유지)
            if order_id:
                try:
                    db = SessionLocal()
                    db_order = get_order_by_order_number(db, order_id)
                    if db_order:
                        resolved_user_id = db_order.user_id
                    db.close()
                except Exception:
                    pass

            # 3. 도구별 필수 인자 주입
            if order_id and mapped_name in ["cancel", "refund", "exchange", "shipping"]:
                clean_args["order_id"] = order_id
            
            # user_id는 모든 도구에 공통 주입
            clean_args["user_id"] = resolved_user_id

            # 4. Tool Call 객체 생성
            tool_calls.append({
                "id": f"call_engine_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": mapped_name,
                    "arguments": json.dumps(clean_args, ensure_ascii=False)
                }
            })

        # 6. 응답 생성 및 로그 출력
        print("-" * 30)
        if tool_calls:
            for tc in tool_calls:
                print(f"[RESPONSE] Tool Call: {tc['function']['name']}({tc['function']['arguments']})")
        else:
            print(f"[RESPONSE] Text Content: {last_message.content}")
        print("="*60)

        finish_reason = "tool_calls" if tool_calls else "stop"
        content_out = str(last_message.content) if last_message.content else None
        if tool_calls and not content_out:
            content_out = "" 

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=ChoiceMessage(
                        content=content_out,
                        tool_calls=tool_calls if tool_calls else None,
                        classification_source=captured_source
                    ),
                    finish_reason=finish_reason
                )
            ]
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)