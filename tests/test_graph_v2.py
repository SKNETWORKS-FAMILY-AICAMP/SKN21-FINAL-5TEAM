import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from langchain_core.messages import HumanMessage
from ecommerce.chatbot.src.graph.workflow import graph_app

async def test_graph():
    print("--- STARTING GRAPH TEST ---")
    
    # 1. Simple Retrieval / Casual Chat Test
    print("\n[Test 1] Casual Chat / Information")
    inputs = {
        "messages": [HumanMessage(content="안녕, 반품 규정 좀 알려줘")],
        "user_id": 1,
        "is_authenticated": True,
        "user_info": {"id": 1, "name": "Test User"}
    }
    
    try:
        result = await graph_app.ainvoke(inputs)
        print("Result keys:", result.keys())
        print("Generation:", result.get("generation"))
        print("Tool Outputs:", result.get("tool_outputs"))
        print("Messages:", len(result.get("messages", [])))
    except Exception as e:
        print(f"Test 1 Failed: {e}")
        import traceback
        traceback.print_exc()

    # 2. Tool Calling Test (Mock Order)
    print("\n[Test 2] Execution Intent (Refund)")
    inputs = {
        "messages": [HumanMessage(content="주문번호 ORD-20240209-0001 환불해줘")],
        "user_id": 1,
        "is_authenticated": True,
        "user_info": {"id": 1, "name": "Test User"}
    }
    
    try:
        # Note: This might fail if DB connection is not available or Order doesn't exist.
        # But we want to see if it tries to call the tool.
        result = await graph_app.ainvoke(inputs)
        print("Generation:", result.get("generation"))
        
        # Check if tool was called
        messages = result.get("messages", [])
        tool_calls = [m for m in messages if hasattr(m, "tool_calls") and m.tool_calls]
        if tool_calls:
             print(f"Tool called: {tool_calls[0].tool_calls[0]['name']}")
        else:
             print("No tool called (might be handled by retrieval or refused)")

    except Exception as e:
        print(f"Test 2 Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_graph())
