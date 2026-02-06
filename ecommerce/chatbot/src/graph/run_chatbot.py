import sys
import os
from dotenv import load_dotenv

# 프로젝트 루트 디렉토리 설정 및 환경 변수 로드
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
sys.path.append(root_path)
load_dotenv(os.path.join(root_path, ".env"))

from langsmith import traceable
from ecommerce.chatbot.src.graph.workflow import graph_app
from langchain_core.messages import HumanMessage

def start_chat():
    print("=== 🤖 무신사 AI 에이전트 인터랙티브 상담 시작 ===")
    print("(종료하려면 '종료' 또는 'exit'를 입력하세요)")
    
    # 세션 상태 유지용 변수 초기화
    current_state = {
        "messages": [],
        "retry_count": 0,
        "user_info": {"name": "테스터", "level": "VIP"},
        "action_status": "idle",
        "order_id": None,
        "action_name": None,
        "documents": [],
        "tool_outputs": []
    }

    while True:
        try:
            user_input = input("\n[USER]: ").strip()
            if not user_input:
                continue
                
            if user_input.lower() in ["종료", "exit", "quit"]:
                print("상담을 종료합니다. 이용해 주셔서 감사합니다!")
                break

            # 사용자 메시지를 상태에 추가
            current_state["messages"].append(HumanMessage(content=user_input))
            
            # 그래프 실행 (이전 상태를 그대로 전달하여 컨텍스트 유지)
            # invoke는 새로운 dict를 반환하므로 이를 현재 상태에 업데이트합니다.
            result = graph_app.invoke(current_state)
            
            # 응답 출력
            ai_msg = result.get("generation")
            print(f"\n[AI]: {ai_msg}")
            
            # 상태 업데이트 (다음 턴을 위해 결과 상태를 통째로 반영)
            current_state = result
            
            # 상태 정보 디버깅 (선택 사항)
            if result.get("action_status") == "pending_approval":
                print(f"  (시스템: {result.get('action_name')} 승인 대기 중...)")

        except KeyboardInterrupt:
            print("\n상담을 종료합니다.")
            break
        except Exception as e:
            print(f"\n[오류 발생]: {e}")

if __name__ == "__main__":
    start_chat()