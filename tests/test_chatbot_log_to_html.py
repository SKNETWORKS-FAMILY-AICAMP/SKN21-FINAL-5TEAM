import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "chatbot_log_to_html.py"
spec = importlib.util.spec_from_file_location("chatbot_log_to_html", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class TestChatbotLogHtml(unittest.TestCase):
    def test_timeline_table_includes_readable_payload_summary(self):
        html = module._timeline_table(
            "Nodes",
            [
                {
                    "event": "start",
                    "node": "agent",
                    "at": "2026-03-03T07:00:00+00:00",
                    "input": {"messages": [{"role": "user", "content": "환불해줘"}]},
                }
            ],
            "node",
        )

        self.assertIn("payload-summary", html)
        self.assertIn("view payload", html)


if __name__ == "__main__":
    unittest.main()
