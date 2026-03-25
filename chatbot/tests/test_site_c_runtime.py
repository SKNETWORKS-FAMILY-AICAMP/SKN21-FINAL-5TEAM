import sys
import json
import os
import subprocess
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

langchain_ollama = types.ModuleType("langchain_ollama")


class _DummyChatOllama:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


langchain_ollama.ChatOllama = _DummyChatOllama
sys.modules.setdefault("langchain_ollama", langchain_ollama)

from chatbot.src.adapters import setup as adapter_setup
from chatbot.src.api.v1.endpoints.chat import _build_current_state
from chatbot.src.schemas.chat import ChatRequest as SharedChatRequest
from chatbot.src.tools import adapter_order_tools


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "ecommerce" / "frontend"
TSC = FRONTEND_ROOT / "node_modules" / ".bin" / "tsc"


class DummyUser:
    def __init__(self, user_id: int = 1, name: str = "Tester", email: str = "tester@example.com"):
        self.id = user_id
        self.name = name
        self.email = email


class DummyRequest:
    def __init__(self, message: str = "환불해줘", site_id: str | None = "site-c"):
        self.message = message
        self.site_id = site_id


def test_get_site_adapter_supports_site_a():
    adapter = adapter_order_tools._get_site_adapter("site-a")

    assert adapter.site_id == "site-a"


def test_resolve_ecommerce_backend_url_uses_localhost_outside_docker(monkeypatch):
    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    monkeypatch.setattr(adapter_setup.os.path, "exists", lambda path: False)

    assert adapter_setup.resolve_ecommerce_backend_url() == "http://localhost:8000"


def test_build_current_state_includes_access_token():
    state = _build_current_state(
        request=DummyRequest(),
        current_user=DummyUser(),
        previous_state={},
        provider="openai",
        model="gpt-5-mini",
        conversation_id="conv-1",
        turn_id="turn-1",
        access_token="token-123",
    )

    assert state["user_info"]["site_id"] == "site-c"
    assert state["user_info"]["access_token"] == "token-123"


def test_build_current_state_accepts_food_session_token():
    state = _build_current_state(
        request=DummyRequest(site_id="site-a"),
        current_user=DummyUser(),
        previous_state={},
        provider="openai",
        model="gpt-5-mini",
        conversation_id="conv-2",
        turn_id="turn-2",
        access_token="session-token-123",
    )

    assert state["user_info"]["site_id"] == "site-a"
    assert state["user_info"]["access_token"] == "session-token-123"


def test_shared_chat_request_accepts_bridge_access_token():
    request = SharedChatRequest(message="안녕", access_token="bridge-token")

    assert request.access_token == "bridge-token"


def test_build_current_state_preserves_previous_site_id_on_follow_up_turn():
    previous_state = {
        "user_info": {
            "site_id": "site-a",
            "access_token": "bridge-token",
        }
    }

    state = _build_current_state(
        request=DummyRequest(site_id=None),
        current_user=DummyUser(),
        previous_state=previous_state,
        provider="openai",
        model="gpt-5-mini",
        conversation_id="conv-3",
        turn_id="turn-3",
        access_token="bridge-token",
    )

    assert state["user_info"]["site_id"] == "site-a"
    assert state["user_info"]["access_token"] == "bridge-token"


def test_site_c_shared_widget_runtime_flow(tmp_path: Path):
    entry = tmp_path / "run_site_c_shared_widget_runtime.tsx"
    css_types = tmp_path / "css-modules.d.ts"
    bootstrap = tmp_path / "run_site_c_shared_widget_runtime.cjs"
    tsconfig = tmp_path / "tsconfig.site-c-shared-widget.json"
    alias_root = tmp_path / "alias-node-modules" / "@shared-chatbot"
    out_dir = tmp_path / "dist"

    css_types.write_text(
        "declare module '*.module.css' {\n"
        "  const classes: Record<string, string>;\n"
        "  export default classes;\n"
        "}\n",
        encoding="utf-8",
    )

    entry.write_text(
        """
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ChatbotWidget,
  bootstrapSharedWidgetAuth,
  normalizeSharedChatResponse,
  sendSharedChatRequest,
} from "@shared-chatbot/ChatbotWidget";

declare const process: {
  stdout: { write: (chunk: string) => void };
  exit: (code: number) => void;
};

async function main() {
  const calls: Array<{ url: string; options: Record<string, unknown> }> = [];

  const fetchMock = async (url: string, options: Record<string, unknown> = {}) => {
    calls.push({ url, options });

    if (url === "/api/chat/auth-token") {
      return {
        ok: true,
        text: async () =>
          JSON.stringify({
            authenticated: true,
            site_id: "site-c",
            access_token: "ecommerce-bridge-token",
          }),
      };
    }

    if (url === "http://localhost:9000/api/chat") {
      return {
        ok: true,
        json: async () => ({
          answer: "주문 목록을 불러왔습니다.",
          conversation_id: "ecommerce-conv-001",
          completed_tasks: [],
          ui_action_required: "show_order_list",
          awaiting_interrupt: false,
          interrupts: [],
          ui_payload: {
            type: "order_list",
            message: "최근 주문 목록입니다.",
            ui_data: [
              {
                order_id: "ORD-001",
                date: "2026-03-19",
                status: "delivered",
                status_label: "배송 완료",
                product_name: "후드 티셔츠",
                amount: 39000,
                can_cancel: false,
                can_return: true,
                can_exchange: true,
              },
            ],
          },
          state: {},
        }),
      };
    }

    throw new Error(`Unexpected URL: ${url}`);
  };

  const host = {
    authBootstrapPath: "/api/chat/auth-token",
    chatbotApiBase: "http://localhost:9000",
  };

  const auth = await bootstrapSharedWidgetAuth(fetchMock, host);
  const response = await sendSharedChatRequest(fetchMock, host, {
    message: "내 주문 보여줘",
    accessToken: auth.accessToken,
    siteId: auth.siteId,
  });
  const messages = normalizeSharedChatResponse(response);
  const markup = renderToStaticMarkup(<ChatbotWidget messages={messages} />);

  process.stdout.write(
    JSON.stringify({
      authenticated: auth.authenticated,
      siteId: auth.siteId,
      calls,
      markup,
    }),
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    tsconfig.write_text(
        (
            "{\n"
            '  "compilerOptions": {\n'
            '    "jsx": "react-jsx",\n'
            '    "module": "commonjs",\n'
            '    "target": "ES2020",\n'
            '    "moduleResolution": "node",\n'
            '    "esModuleInterop": true,\n'
            '    "skipLibCheck": true,\n'
            f'    "outDir": "{out_dir}",\n'
            f'    "baseUrl": "{FRONTEND_ROOT}",\n'
            '    "paths": {\n'
            f'      "@shared-chatbot/*": ["{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "*"}"]\n'
            '    },\n'
            f'    "typeRoots": ["{FRONTEND_ROOT / "node_modules" / "@types"}"]\n'
            "  },\n"
            '  "include": [\n'
            f'    "{entry}",\n'
            f'    "{css_types}",\n'
            f'    "{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "**" / "*.ts"}",\n'
            f'    "{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "**" / "*.tsx"}"\n'
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    alias_root.mkdir(parents=True, exist_ok=True)

    try:
        compile_result = subprocess.run(
            [str(TSC), "-p", str(tsconfig)],
            cwd=FRONTEND_ROOT,
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, compile_result.stderr or compile_result.stdout

        emitted = next(out_dir.rglob("run_site_c_shared_widget_runtime.js"))
        shared_widget_js = next(out_dir.rglob("ChatbotWidget.js"))
        (shared_widget_js.parent / "chatbot-widget.module.css").write_text("", encoding="utf-8")
        (alias_root / "ChatbotWidget.js").write_text(
            f'module.exports = require("{shared_widget_js}");\n',
            encoding="utf-8",
        )
        bootstrap.write_text(
            """
require.extensions[".css"] = (module) => {
  module.exports = {};
};
require("__EMITTED__");
""".strip().replace("__EMITTED__", str(emitted)),
            encoding="utf-8",
        )

        run_result = subprocess.run(
            ["node", str(bootstrap)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "NODE_PATH": os.pathsep.join(
                    [
                        str(tmp_path / "alias-node-modules"),
                        str(FRONTEND_ROOT / "node_modules"),
                    ]
                ),
            },
        )

        assert run_result.returncode == 0, run_result.stderr
        payload = json.loads(run_result.stdout)
        assert payload["authenticated"] is True
        assert payload["siteId"] == "site-c"
        request_body = json.loads(payload["calls"][1]["options"]["body"])
        assert request_body["site_id"] == "site-c"
        assert request_body["access_token"] == "ecommerce-bridge-token"
        assert "주문 목록을 불러왔습니다." in payload["markup"]
        assert "최근 주문 목록입니다." in payload["markup"]
        assert "후드 티셔츠" in payload["markup"]
    finally:
        (alias_root / "ChatbotWidget.js").unlink(missing_ok=True)
