import asyncio
import os
import sys
import json

# Add project root to path
sys.path.append(os.getcwd())

from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from ecommerce.chatbot.src.graph.workflow import graph_app

async def test_safety_features():
    print("--- STARTING SAFETY FEATURES TEST ---")
    
    # 1. Smart Validation Test (Refund without ID)
    print("\n[Test 1] Smart Validation (Missing Order ID)")
    inputs = {
        "messages": [HumanMessage(content="환불해줘")],
        "user_id": 1,
        "is_authenticated": True,
        "user_info": {"id": 1, "name": "Test User"}
    }
    
    try:
        result = await graph_app.ainvoke(inputs)
        msgs = result.get("messages", [])
        last_ai_msg = None
        for m in reversed(msgs):
            if isinstance(m, AIMessage) and m.tool_calls:
                last_ai_msg = m
                break
        
        if last_ai_msg:
            # We expect 'get_user_orders'
            tool_name = last_ai_msg.tool_calls[0]["name"]
            tool_args = last_ai_msg.tool_calls[0]["args"]
            print(f"Final tool call: {tool_name}")
            print(f"Args: {tool_args}")
            
            if tool_name == "get_user_orders" and tool_args.get("requires_selection"):
                print("SUCCESS: Validation correctly redirected to get_user_orders.")
            elif tool_name in ["check_refund_eligibility", "cancel_order"]:
                print("FAILURE: Validation failed to catch missing ID.")
            else:
                print(f"OBSERVATION: Agent called {tool_name} directly.")
        else:
            print("FAILURE: No tool call found.")

    except Exception as e:
        print(f"Test 1 Failed: {e}")


    # 2. Human Approval Test (Sensitive Action with Valid ID)
    print("\n[Test 2] Human Approval (Sensitive Action)")
    # Use a valid order ID found in the previous Log or DB
    inputs_2 = {
        "messages": [HumanMessage(content="주문번호 ORD-20260211-0003 취소해줘")],
        "user_id": 1,
        "is_authenticated": True,
        "user_info": {"id": 1, "name": "Test User"}
    }
    
    try:
        result_2 = await graph_app.ainvoke(inputs_2)
        
        # Check if we stopped at Approval
        action_status = result_2.get("action_status")
        tool_outputs = result_2.get("tool_outputs", [])
        
        print(f"Action Status: {action_status}")
        print(f"Tool Outputs: {tool_outputs}")
        
        if action_status == "pending_approval":
            confirmation_shown = any(to.get("ui_action") == "show_confirmation" for to in tool_outputs)
            if confirmation_shown:
                print("SUCCESS: Approval node intercepted and requested confirmation.")
            else:
                print("FAILURE: Status is pending but no UI action generated.")
        else:
            # Maybe the ID was invalid and validation redirected? 
            # Or LLM refused?
            print(f"FAILURE: Expected pending_approval, got {action_status}")

    except Exception as e:
        print(f"Test 2 Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_safety_features())
