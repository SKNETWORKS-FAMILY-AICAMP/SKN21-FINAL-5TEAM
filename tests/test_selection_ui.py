import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from langchain_core.messages import HumanMessage
from ecommerce.chatbot.src.graph.workflow import graph_app

async def test_order_selection():
    print("--- STARTING ORDER SELECTION UI TEST ---")
    
    # User asks for refund without specifying order ID
    print("\n[Test] Refund Request (No Order ID)")
    inputs = {
        "messages": [HumanMessage(content="환불해줘")],
        "user_id": 1,
        "is_authenticated": True,
        "user_info": {"id": 1, "name": "Test User"}
    }
    
    try:
        # Run the graph
        result = await graph_app.ainvoke(inputs)
        
        # Check tool calls
        messages = result.get("messages", [])
        tool_calls = [m for m in messages if hasattr(m, "tool_calls") and m.tool_calls]
        
        if tool_calls:
            first_tool_call = tool_calls[0].tool_calls[0]
            print(f"Tool called: {first_tool_call['name']}")
            print(f"Tool args: {first_tool_call['args']}")
            
            # Validation
            if first_tool_call['name'] == 'get_user_orders':
                args = first_tool_call['args']
                if args.get('requires_selection') is True:
                    print("SUCCESS: 'requires_selection=True' was correctly set.")
                else:
                    print(f"FAILURE: 'requires_selection' is {args.get('requires_selection')}, expected True.")
            else:
                 print(f"FAILURE: Expected 'get_user_orders', got '{first_tool_call['name']}'")
        else:
             print("FAILURE: No tool called.")
             print("Generation:", result.get("generation"))

    except Exception as e:
        print(f"Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_order_selection())
