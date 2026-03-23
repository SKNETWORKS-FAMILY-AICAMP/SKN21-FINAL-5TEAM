from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "ecommerce" / "frontend"
TSC = FRONTEND_ROOT / "node_modules" / ".bin" / "tsc"


def _run_typescript_transport(
    tmp_path: Path,
    *,
    entry_name: str,
    bootstrap_name: str,
    tsconfig_name: str,
    source: str,
) -> str:
    entry = tmp_path / entry_name
    css_types = tmp_path / "css-modules.d.ts"
    bootstrap = tmp_path / bootstrap_name
    tsconfig = tmp_path / tsconfig_name
    shared_alias_root = tmp_path / "alias-node-modules" / "@shared-chatbot"
    ecommerce_alias_root = tmp_path / "alias-node-modules" / "@ecommerce-chatbot"
    out_dir = tmp_path / "dist"

    css_types.write_text(
        "declare module '*.module.css' {\n"
        "  const classes: Record<string, string>;\n"
        "  export default classes;\n"
        "}\n",
        encoding="utf-8",
    )
    entry.write_text(source.strip() + "\n", encoding="utf-8")
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
            f'      "@shared-chatbot/*": ["{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "*"}"],\n'
            f'      "@ecommerce-chatbot/*": ["{REPO_ROOT / "ecommerce" / "frontend" / "app" / "chatbot" / "*"}"]\n'
            '    },\n'
            f'    "typeRoots": ["{FRONTEND_ROOT / "node_modules" / "@types"}"]\n'
            "  },\n"
            '  "include": [\n'
            f'    "{entry}",\n'
            f'    "{css_types}",\n'
            f'    "{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "**" / "*.ts"}",\n'
            f'    "{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "**" / "*.tsx"}",\n'
            f'    "{REPO_ROOT / "ecommerce" / "frontend" / "app" / "chatbot" / "**" / "*.ts"}",\n'
            f'    "{REPO_ROOT / "ecommerce" / "frontend" / "app" / "chatbot" / "**" / "*.tsx"}"\n'
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    compile_result = subprocess.run(
        [str(TSC), "-p", str(tsconfig)],
        cwd=FRONTEND_ROOT,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr or compile_result.stdout

    emitted = next(out_dir.rglob(entry_name.replace(".tsx", ".js")))
    shared_widget_js = next(out_dir.rglob("ChatbotWidget.js"))
    ecommerce_product_list_js = next(out_dir.rglob("ProductListUI.js"))
    (shared_widget_js.parent / "chatbot-widget.module.css").write_text("", encoding="utf-8")
    shared_alias_root.mkdir(parents=True, exist_ok=True)
    ecommerce_alias_root.mkdir(parents=True, exist_ok=True)
    (shared_alias_root / "ChatbotWidget.js").write_text(
        f'module.exports = require("{shared_widget_js}");\n',
        encoding="utf-8",
    )
    (ecommerce_alias_root / "ProductListUI.js").write_text(
        f'module.exports = require("{ecommerce_product_list_js}");\n',
        encoding="utf-8",
    )
    bootstrap.write_text(
        """
require.extensions[".css"] = (module) => {
  module.exports = {};
};
const Module = require("module");
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === "next/navigation") {
    return { useRouter: () => ({ push() {} }) };
  }
  if (request === "../authcontext" || request.endsWith("/authcontext")) {
    return { useAuth: () => ({ isLoggedIn: true }) };
  }
  return originalLoad.apply(this, arguments);
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
    return run_result.stdout


def test_chat_auth_token_endpoint_returns_bridge_contract(monkeypatch) -> None:
    fake_workflow_module = ModuleType("chatbot.src.graph.workflow")
    fake_workflow_module.graph_app = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "chatbot.src.graph.workflow", fake_workflow_module)

    from chatbot.src.api.v1.endpoints import chat as chat_endpoint

    test_app = FastAPI()
    test_app.include_router(chat_endpoint.router, prefix="/api/v1/chat")
    test_app.dependency_overrides[chat_endpoint.get_current_user_optional] = lambda: SimpleNamespace(
        id=7,
        email="tester@example.com",
        name="Tester",
    )

    client = TestClient(test_app)
    client.cookies.set("access_token", "cookie-token-123")
    response = client.post("/api/v1/chat/auth-token")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "access_token": "cookie-token-123",
        "site_id": "site-c",
        "user": {
            "id": "7",
            "email": "tester@example.com",
            "name": "Tester",
        },
    }


def test_shared_widget_transport_bootstraps_auth_and_streams_shared_chat(tmp_path: Path) -> None:
    entry = tmp_path / "run_shared_widget_transport.tsx"
    css_types = tmp_path / "css-modules.d.ts"
    bootstrap = tmp_path / "run_shared_widget_transport.cjs"
    tsconfig = tmp_path / "tsconfig.shared-widget-transport.json"
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
  streamSharedChatResponse,
  type SharedChatMessage,
} from "@shared-chatbot/ChatbotWidget";

declare const process: {
  stdout: {
    write: (chunk: string) => void;
  };
  exit: (code?: number) => void;
};

type FetchCall = {
  url: string;
  body: unknown;
};

const fetchCalls: FetchCall[] = [];

const fakeFetch = async (url: string, init?: { body?: string }) => {
  fetchCalls.push({
    url,
    body: init?.body ? JSON.parse(init.body) : null,
  });

  if (url === "/api/chat/auth-token") {
    return {
      ok: true,
      json: async () => ({
        authenticated: true,
        site_id: "site-c",
        access_token: "bridge-token-123",
        user: {
          id: "7",
          email: "tester@example.com",
          name: "Tester",
        },
      }),
    };
  }

  if (url === "http://localhost:9000/api/v1/chat/stream") {
    const events = [
          'data: {"type":"ui_action","ui_action":"show_product_list","message":"추천 상품","ui_data":[{"id":1,"name":"테스트 상품","price":12000}]}\\n\\n',
          'data: {"type":"metadata","state":{"conversation_id":"conv-123","user_info":{"site_id":"site-c","access_token":"bridge-token-123"}}}\\n\\n',
          'data: {"type":"done"}\\n\\n',
    ];

    let index = 0;

    return {
      ok: true,
      text: async () => "",
      body: {
        getReader() {
          return {
            async read() {
              if (index >= events.length) {
                return { done: true, value: undefined };
              }

              const value = new TextEncoder().encode(events[index]);
              index += 1;
              return { done: false, value };
            },
          };
        },
      },
    };
  }

  throw new Error(`Unexpected fetch URL: ${url}`);
};

async function main() {
  const auth = await bootstrapSharedWidgetAuth(
    fakeFetch as typeof fetch,
    {
      authBootstrapPath: "/api/chat/auth-token",
      chatbotApiBase: "http://localhost:9000",
    },
  );

  const messages: SharedChatMessage[] = [];
  let nextState: unknown = null;

  await streamSharedChatResponse(
    {
      host: {
        authBootstrapPath: "/api/chat/auth-token",
        chatbotApiBase: "http://localhost:9000",
      },
      message: "추천 상품 보여줘",
      previousState: null,
      bootstrap: auth,
      fetchImpl: fakeFetch as typeof fetch,
    },
    {
      onMessage(message) {
        messages.push(message);
      },
      onStateChange(state) {
        nextState = state;
      },
    },
  );

  const markup = renderToStaticMarkup(<ChatbotWidget messages={messages} />);
  process.stdout.write(JSON.stringify({ fetchCalls, markup, nextState }));
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

    command = [
        str(TSC),
        "-p",
        str(tsconfig),
    ]

    result = subprocess.run(
        command,
        cwd=FRONTEND_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    emitted = next(out_dir.rglob("run_shared_widget_transport.js"))
    shared_widget_js = next(out_dir.rglob("ChatbotWidget.js"))
    (shared_widget_js.parent / "chatbot-widget.module.css").write_text("", encoding="utf-8")
    alias_root.mkdir(parents=True, exist_ok=True)
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
    assert payload["fetchCalls"][0]["url"] == "/api/chat/auth-token"
    assert payload["fetchCalls"][1]["url"] == "http://localhost:9000/api/v1/chat/stream"
    assert payload["fetchCalls"][1]["body"]["site_id"] == "site-c"
    assert payload["fetchCalls"][1]["body"]["access_token"] == "bridge-token-123"
    assert "추천 상품" in payload["markup"]
    assert "테스트 상품" in payload["markup"]
    assert payload["nextState"]["conversation_id"] == "conv-123"


def test_ecommerce_wrapper_enables_full_shared_widget_capabilities(tmp_path: Path) -> None:
    chatbotfab_source = (
        REPO_ROOT / "ecommerce" / "frontend" / "app" / "chatbot" / "chatbotfab.tsx"
    ).read_text(encoding="utf-8")

    assert "capabilities={ECOMMERCE_SHARED_WIDGET_CAPABILITIES}" in chatbotfab_source

    output = _run_typescript_transport(
        tmp_path,
        entry_name="render_ecommerce_wrapper.tsx",
        bootstrap_name="run_render_ecommerce_wrapper.cjs",
        tsconfig_name="tsconfig.ecommerce-wrapper.json",
        source="""
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChatbotWidget } from "@shared-chatbot/ChatbotWidget";
import ProductListUI from "@ecommerce-chatbot/ProductListUI";

declare const process: {
  stdout: {
    write: (chunk: string) => void;
  };
};

const markup = renderToStaticMarkup(
  <ChatbotWidget
    capabilities="full"
    messages={[
      {
        type: "product_list",
        message: "추천 상품",
        products: [{ id: 1, name: "테스트 상품", price: 12000 }],
      },
    ]}
    renderProductList={(message) => <ProductListUI products={message.products} message={message.message} />}
  />,
);

process.stdout.write(
  JSON.stringify({
    capabilities: "full",
    markup,
  }),
);
        """,
    )

    payload = json.loads(output)
    assert payload["capabilities"] == "full"
    assert "장바구니" in payload["markup"]
