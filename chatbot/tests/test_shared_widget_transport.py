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
TOOLING_ROOT = REPO_ROOT if (REPO_ROOT / "node_modules" / ".bin" / "tsc").exists() else REPO_ROOT.parents[1]
FRONTEND_ROOT = REPO_ROOT / "ecommerce" / "frontend"
TSC = TOOLING_ROOT / "node_modules" / ".bin" / "tsc"

os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")
fake_langchain_ollama = ModuleType("langchain_ollama")
fake_langchain_ollama.ChatOllama = type("ChatOllama", (), {})
sys.modules.setdefault("langchain_ollama", fake_langchain_ollama)


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
    skn_alias_root = tmp_path / "alias-node-modules" / "@skn" / "shared-chatbot"
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
            '    "types": ["node", "react", "react-dom"],\n'
            f'    "outDir": "{out_dir}",\n'
            f'    "baseUrl": "{FRONTEND_ROOT}",\n'
            '    "paths": {\n'
            f'      "@shared-chatbot/*": ["{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "*"}"],\n'
            f'      "react": ["{TOOLING_ROOT / "node_modules" / "react"}"],\n'
            f'      "react-dom/server": ["{TOOLING_ROOT / "node_modules" / "react-dom" / "server"}"],\n'
            f'      "react/jsx-runtime": ["{TOOLING_ROOT / "node_modules" / "react" / "jsx-runtime"}"],\n'
            f'      "react-markdown": ["{TOOLING_ROOT / "node_modules" / "react-markdown"}"]\n'
            '    },\n'
            f'    "typeRoots": ["{TOOLING_ROOT / "node_modules" / "@types"}"]\n'
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

    compile_result = subprocess.run(
        [str(TSC), "-p", str(tsconfig)],
        cwd=FRONTEND_ROOT,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr or compile_result.stdout

    emitted = next(out_dir.rglob(entry_name.replace(".tsx", ".js")))
    shared_index_js = next(out_dir.rglob("index.js"))
    shared_widget_js = next(out_dir.rglob("ChatbotWidget.js"))
    shared_product_list_js = next(out_dir.rglob("ProductListUI.js"))
    for css_name in (
        "chatbot-widget.module.css",
        "chatbotfab.module.css",
        "productlist.module.css",
        "reviewform.module.css",
        "usedsaleform.module.css",
    ):
        (shared_widget_js.parent / css_name).write_text("", encoding="utf-8")
    shared_alias_root.mkdir(parents=True, exist_ok=True)
    skn_alias_root.mkdir(parents=True, exist_ok=True)
    (shared_alias_root / "index.js").write_text(
        f'module.exports = require("{shared_index_js}");\n',
        encoding="utf-8",
    )
    (shared_alias_root / "ChatbotWidget.js").write_text(
        f'module.exports = require("{shared_widget_js}");\n',
        encoding="utf-8",
    )
    (shared_alias_root / "ProductListUI.js").write_text(
        f'module.exports = require("{shared_product_list_js}");\n',
        encoding="utf-8",
    )
    (skn_alias_root / "ChatbotWidget.js").write_text(
        f'module.exports = require("{shared_widget_js}");\n',
        encoding="utf-8",
    )
    bootstrap.write_text(
        """
require.extensions[".css"] = (module) => {
  module.exports = {};
};
const Module = require("module");
const originalLoad = Module._load;
const Fragment = Symbol.for("react.fragment");
const normalizeChildren = (children) => {
  if (children === undefined || children === null) return [];
  return Array.isArray(children) ? children.flat(Infinity) : [children];
};
const reactStub = {
  Fragment,
  createElement(type, props, ...children) {
    return {
      type,
      props: {
        ...(props || {}),
        children: children.length <= 1 ? children[0] : children,
      },
    };
  },
  useState(initial) {
    const value = typeof initial === "function" ? initial() : initial;
    return [value, () => {}];
  },
  useEffect() {},
  useMemo(factory) {
    return factory();
  },
  useRef(value) {
    return { current: value };
  },
};
const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
const renderNode = (node) => {
  if (node === null || node === undefined || node === false || node === true) {
    return "";
  }
  if (Array.isArray(node)) {
    return node.map(renderNode).join("");
  }
  if (typeof node === "string" || typeof node === "number") {
    return escapeHtml(node);
  }
  if (typeof node.type === "function") {
    return renderNode(node.type(node.props || {}));
  }
  if (node.type === Fragment) {
    return renderNode(node.props?.children);
  }

  const props = node.props || {};
  const attrs = Object.entries(props)
    .filter(([key, value]) => key !== "children" && key !== "ref" && !key.startsWith("on") && value !== false && value != null)
    .map(([key, value]) => {
      const attrName = key === "className" ? "class" : key;
      if (typeof value === "boolean") {
        return ` ${attrName}="${value ? "true" : "false"}"`;
      }
      return ` ${attrName}="${escapeHtml(value)}"`;
    })
    .join("");
  return `<${node.type}${attrs}>${normalizeChildren(props.children).map(renderNode).join("")}</${node.type}>`;
};
const jsxRuntimeStub = {
  Fragment,
  jsx(type, props) {
    return { type, props: props || {} };
  },
  jsxs(type, props) {
    return { type, props: props || {} };
  },
};
Module._load = function(request, parent, isMain) {
  if (request === "react") {
    return reactStub;
  }
  if (request === "react/jsx-runtime") {
    return jsxRuntimeStub;
  }
  if (request === "react-dom/server") {
    return { renderToStaticMarkup: renderNode };
  }
  if (request === "react-markdown") {
    return ({ children }) => children;
  }
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
                    str(TOOLING_ROOT / "node_modules"),
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
    skn_alias_root = tmp_path / "alias-node-modules" / "@skn" / "shared-chatbot"
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
  ensureFloatingLauncherBootstrapOnOpen,
  bootstrapSharedWidgetAuth,
  streamSharedChatResponse,
  type SharedChatMessage,
} from "@shared-chatbot/index";

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
  const closedBootstrap = await ensureFloatingLauncherBootstrapOnOpen({
    isOpen: false,
    bootstrap: null,
    host: {
      authBootstrapPath: "/api/chat/auth-token",
      chatbotApiBase: "http://localhost:9000",
    },
    fetchImpl: fakeFetch as typeof fetch,
  });

  const auth = await ensureFloatingLauncherBootstrapOnOpen({
    isOpen: true,
    bootstrap: closedBootstrap,
    host: {
      authBootstrapPath: "/api/chat/auth-token",
      chatbotApiBase: "http://localhost:9000",
    },
    fetchImpl: fakeFetch as typeof fetch,
  });

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
  process.stdout.write(JSON.stringify({ closedBootstrap, fetchCalls, markup, nextState }));
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
            '    "types": ["node", "react", "react-dom"],\n'
            f'    "outDir": "{out_dir}",\n'
            f'    "baseUrl": "{FRONTEND_ROOT}",\n'
            '    "paths": {\n'
            f'      "@shared-chatbot/*": ["{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "*"}"],\n'
            f'      "react": ["{TOOLING_ROOT / "node_modules" / "react"}"],\n'
            f'      "react-dom/server": ["{TOOLING_ROOT / "node_modules" / "react-dom" / "server"}"],\n'
            f'      "react/jsx-runtime": ["{TOOLING_ROOT / "node_modules" / "react" / "jsx-runtime"}"],\n'
            f'      "react-markdown": ["{TOOLING_ROOT / "node_modules" / "react-markdown"}"]\n'
            '    },\n'
            f'    "typeRoots": ["{TOOLING_ROOT / "node_modules" / "@types"}"]\n'
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
    shared_index_js = next(out_dir.rglob("index.js"))
    for css_name in (
        "chatbot-widget.module.css",
        "chatbotfab.module.css",
        "productlist.module.css",
        "reviewform.module.css",
        "usedsaleform.module.css",
    ):
        (shared_widget_js.parent / css_name).write_text("", encoding="utf-8")
    alias_root.mkdir(parents=True, exist_ok=True)
    skn_alias_root.mkdir(parents=True, exist_ok=True)
    (alias_root / "index.js").write_text(
        f'module.exports = require("{shared_index_js}");\n',
        encoding="utf-8",
    )
    (alias_root / "ChatbotWidget.js").write_text(
        f'module.exports = require("{shared_widget_js}");\n',
        encoding="utf-8",
    )
    (skn_alias_root / "ChatbotWidget.js").write_text(
        f'module.exports = require("{shared_widget_js}");\n',
        encoding="utf-8",
    )
    bootstrap.write_text(
        """
require.extensions[".css"] = (module) => {
  module.exports = {};
};
const Module = require("module");
const originalLoad = Module._load;
const Fragment = Symbol.for("react.fragment");
const reactStub = {
  Fragment,
  createElement(type, props, ...children) {
    return {
      type,
      props: {
        ...(props || {}),
        children: children.length <= 1 ? children[0] : children,
      },
    };
  },
  useState(initial) {
    const value = typeof initial === "function" ? initial() : initial;
    return [value, () => {}];
  },
  useEffect() {},
  useMemo(factory) {
    return factory();
  },
  useRef(value) {
    return { current: value };
  },
};
const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
const renderNode = (node) => {
  if (node === null || node === undefined || node === false || node === true) {
    return "";
  }
  if (Array.isArray(node)) {
    return node.map(renderNode).join("");
  }
  if (typeof node === "string" || typeof node === "number") {
    return escapeHtml(node);
  }
  if (typeof node.type === "function") {
    return renderNode(node.type(node.props || {}));
  }
  if (node.type === Fragment) {
    const children = node.props?.children;
    return Array.isArray(children) ? children.map(renderNode).join("") : renderNode(children);
  }
  const props = node.props || {};
  const attrs = Object.entries(props)
    .filter(([key, value]) => key !== "children" && key !== "ref" && !key.startsWith("on") && value !== false && value != null)
    .map(([key, value]) => {
      const attrName = key === "className" ? "class" : key;
      if (typeof value === "boolean") {
        return ` ${attrName}="${value ? "true" : "false"}"`;
      }
      return ` ${attrName}="${escapeHtml(value)}"`;
    })
    .join("");
  const children = props.children;
  const renderedChildren = Array.isArray(children) ? children.map(renderNode).join("") : renderNode(children);
  return `<${node.type}${attrs}>${renderedChildren}</${node.type}>`;
};
const jsxRuntimeStub = {
  Fragment,
  jsx(type, props) {
    return { type, props: props || {} };
  },
  jsxs(type, props) {
    return { type, props: props || {} };
  },
};
Module._load = function(request, parent, isMain) {
  if (request === "react") {
    return reactStub;
  }
  if (request === "react/jsx-runtime") {
    return jsxRuntimeStub;
  }
  if (request === "react-dom/server") {
    return { renderToStaticMarkup: renderNode };
  }
  if (request === "react-markdown") {
    return ({ children }) => children;
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
                    str(TOOLING_ROOT / "node_modules"),
                ]
            ),
        },
    )

    assert run_result.returncode == 0, run_result.stderr
    payload = json.loads(run_result.stdout)
    assert payload["closedBootstrap"] is None
    assert payload["fetchCalls"][0]["url"] == "/api/chat/auth-token"
    assert payload["fetchCalls"][1]["url"] == "http://localhost:9000/api/v1/chat/stream"
    assert payload["fetchCalls"][1]["body"]["site_id"] == "site-c"
    assert payload["fetchCalls"][1]["body"]["access_token"] == "bridge-token-123"
    assert "추천 상품" in payload["markup"]
    assert "테스트 상품" in payload["markup"]
    assert payload["nextState"]["conversation_id"] == "conv-123"


def test_ecommerce_wrapper_enables_full_shared_widget_capabilities(tmp_path: Path) -> None:
    chatbotfab_source = (
        REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "chatbotfab.tsx"
    ).read_text(encoding="utf-8")

    assert 'capabilities="full"' in chatbotfab_source

    output = _run_typescript_transport(
        tmp_path,
        entry_name="render_ecommerce_wrapper.tsx",
        bootstrap_name="run_render_ecommerce_wrapper.cjs",
        tsconfig_name="tsconfig.ecommerce-wrapper.json",
        source="""
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChatbotWidget } from "@shared-chatbot/ChatbotWidget";
import ProductListUI from "@shared-chatbot/ProductListUI";

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


def test_shared_widget_transport_promotes_metadata_pending_option_interrupt(tmp_path: Path) -> None:
    output = _run_typescript_transport(
        tmp_path,
        entry_name="run_shared_widget_pending_option_interrupt.tsx",
        bootstrap_name="run_shared_widget_pending_option_interrupt.cjs",
        tsconfig_name="tsconfig.shared-widget-pending-option-interrupt.json",
        source="""
import {
  streamSharedChatResponse,
  type SharedChatMessage,
} from "@shared-chatbot/ChatbotWidget";

declare const process: {
  stdout: {
    write: (chunk: string) => void;
  };
  exit: (code?: number) => void;
};

const fakeFetch = async (_url: string, _init?: { body?: string }) => {
  const events = [
    'data: {"type":"metadata","ui_action_required":"show_option_list","state":{"conversation_id":"conv-opt-123","awaiting_interrupt":true,"pending_interrupt":[{"ui_action":"show_option_list","action":"select_option","message":"교환할 옵션을 선택해주세요.","ui_data":[{"option_id":12361,"label":"옵션 12361 · 사이즈 M · 색상 블랙 · 재고 3","size_name":"M","color":"블랙","quantity":3}],"prior_action":"exchange"}]}}\\n\\n',
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
};

async function main() {
  const unhandled: Array<Record<string, unknown>> = [];
  let nextState: unknown = null;
  const messages: SharedChatMessage[] = [];

  await streamSharedChatResponse(
    {
      host: {
        authBootstrapPath: "/api/chat/auth-token",
        chatbotApiBase: "http://localhost:9000",
      },
      message: "옵션 변경할래",
      previousState: null,
      bootstrap: {
        authenticated: true,
        site_id: "site-c",
        siteId: "site-c",
        access_token: "bridge-token-123",
        accessToken: "bridge-token-123",
      },
      fetchImpl: fakeFetch as typeof fetch,
    },
    {
      onMessage(message) {
        messages.push(message);
      },
      onUnhandledUiAction(payload) {
        unhandled.push(payload);
      },
      onStateChange(state) {
        nextState = state;
      },
    },
  );

  process.stdout.write(JSON.stringify({ unhandled, nextState, messages }));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
        """,
    )

    payload = json.loads(output)
    assert payload["messages"] == []
    assert payload["unhandled"] == [
        {
            "ui_action": "show_option_list",
            "action": "select_option",
            "message": "교환할 옵션을 선택해주세요.",
            "ui_data": [
                {
                    "option_id": 12361,
                    "label": "옵션 12361 · 사이즈 M · 색상 블랙 · 재고 3",
                    "size_name": "M",
                    "color": "블랙",
                    "quantity": 3,
                }
            ],
            "prior_action": "exchange",
        }
    ]
    assert payload["nextState"] == {
        "conversation_id": "conv-opt-123",
        "awaiting_interrupt": True,
        "pending_interrupt": [
            {
                "ui_action": "show_option_list",
                "action": "select_option",
                "message": "교환할 옵션을 선택해주세요.",
                "ui_data": [
                    {
                        "option_id": 12361,
                        "label": "옵션 12361 · 사이즈 M · 색상 블랙 · 재고 3",
                        "size_name": "M",
                        "color": "블랙",
                        "quantity": 3,
                    }
                ],
                "prior_action": "exchange",
            }
        ],
    }
