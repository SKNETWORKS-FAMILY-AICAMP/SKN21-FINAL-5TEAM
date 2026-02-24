
import json
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.append(os.getcwd())

try:
    from langchain_core.utils.function_calling import convert_to_openai_function
    from ecommerce.chatbot.src.graph.nodes_v2 import TOOLS
    
    tools_schema = []
    for tool in TOOLS:
        # Pydantic v1/v2 호환성 문제 방지 및 정확한 스키마 추출
        openai_tool = convert_to_openai_function(tool)
        # FunctionChat-Bench 포맷에 맞게 래핑
        tools_schema.append({
            "type": "function",
            "function": openai_tool
        })
        
    print(json.dumps(tools_schema, ensure_ascii=False, indent=2))
    
except Exception as e:
    import traceback
    traceback.print_exc()
