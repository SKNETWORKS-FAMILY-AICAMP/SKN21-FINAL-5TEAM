import os
import sys

sys.path.append(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)

from ecommerce.chatbot.src.graph.workflow import graph_app
from ecommerce.chatbot.src.graph.state import AgentState


def run_test(test_name: str, message: str):
    print(f"\n{'=' * 50}")
    print(f"TEST: {test_name}")
    print(f"MESSAGE: '{message}'")
    print(f"{'=' * 50}")

    state = {
        "messages": [("user", message)],
        "question": message,
        "generation": "",
        "documents": [],
        "refined_context": "",
        "category": None,
        "intent_type": "info_search",
        "is_authenticated": True,
        "user_info": {"id": 1, "name": "Test User"},
        "tool_outputs": [],
        "task_list": [],
        "task_results": [],
        "current_task": None,
        "is_safe": True,
        "safe_message": None,
        "is_relevant": True,
        "is_general_chat": False,
        "retry_count": 0,
        "requires_selection": False,
        "is_evaluation": False,
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "conversation_id": "test_conv_id",
        "turn_id": "test_turn_id",
    }

    config = {"configurable": {"thread_id": "test_thread_123"}}

    try:
        final_state = graph_app.invoke(state, config=config)
        print(f"\n[Result Generation]")
        print(final_state.get("generation"))

        print(f"\n[Task List]")
        for task in final_state.get("task_list", []):
            print(f"- {task}")

    except Exception as e:
        print(f"\nError: {e}")


def main():
    # 1. Guardrail Safe & Normal Routing (RAG/POLICY) Test
    run_test("Safe Policy Check", "배송조회 어떻게 해?")

    # 2. Guardrail Unsafe Test (주민번호/비방어)
    run_test(
        "Unsafe PII Check",
        "내 주민번호는 900101-1234567 이야. 욕설이 포함될 수 있어 씨발",
    )

    # 3. New Intent Task Type Test
    run_test("New Intent (RECOMMEND)", "에 어울리는 옷 추천해줘.")


if __name__ == "__main__":
    main()
