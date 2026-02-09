import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ecommerce.chatbot.src.tools.order_tools import get_order_details, get_delivery_status
from ecommerce.chatbot.src.tools.service_tools import get_reviews

def test_tools():
    print("=== Testing Order Tools (Real DB) ===")
    order_id = "ORD-20240209-0001"
    
    print(f"\n1. get_order_details('{order_id}')")
    result = get_order_details.invoke(order_id)
    print(result)

    print(f"\n2. get_delivery_status('{order_id}')")
    result = get_delivery_status.invoke(order_id)
    print(result)
    
    print("\n=== Testing Service Tools (Real DB) ===")
    print("\n3. get_reviews() (All reviews)")
    # We haven't created reviews yet, so this might be empty
    result = get_reviews.invoke({})
    print(result)

if __name__ == "__main__":
    test_tools()
