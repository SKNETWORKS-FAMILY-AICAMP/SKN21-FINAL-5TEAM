import unittest

from langchain_core.messages import AIMessage, HumanMessage

from chatbot.src.infrastructure.conversation_logger import safe_serialize


class TestConversationLoggerSerialization(unittest.TestCase):
    def test_messages_are_compacted_for_debug_readability(self):
        state = {
            "messages": [
                HumanMessage(content="첫 메시지"),
                AIMessage(content="두 번째 응답"),
                HumanMessage(content="세 번째 메시지"),
                AIMessage(content="네 번째 응답"),
            ],
            "question": "환불 진행",
        }

        serialized = safe_serialize(state)
        messages = serialized.get("messages")

        self.assertIsInstance(messages, dict)
        self.assertEqual(messages.get("_kind"), "messages_preview")
        self.assertEqual(messages.get("count"), 4)
        self.assertIn("last", messages)

    def test_large_generic_list_is_compacted(self):
        payload = {"numbers": list(range(20))}

        serialized = safe_serialize(payload)
        numbers = serialized.get("numbers")

        self.assertIsInstance(numbers, dict)
        self.assertEqual(numbers.get("_kind"), "list_preview")
        self.assertEqual(numbers.get("count"), 20)
        self.assertTrue(numbers.get("truncated"))


if __name__ == "__main__":
    unittest.main()
