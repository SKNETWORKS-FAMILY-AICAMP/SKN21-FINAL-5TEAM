from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "ecommerce" / "frontend"
TSC = FRONTEND_ROOT / "node_modules" / ".bin" / "tsc"


def _run_shared_widget_typescript(
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
    alias_root = tmp_path / "alias-node-modules" / "@shared-chatbot"
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

    try:
        compile_result = subprocess.run(
            [str(TSC), "-p", str(tsconfig)],
            cwd=FRONTEND_ROOT,
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, compile_result.stderr or compile_result.stdout

        emitted = next(out_dir.rglob(entry_name.replace(".tsx", ".js")))
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
        return run_result.stdout
    finally:
        if alias_root.exists():
            (alias_root / "ChatbotWidget.js").unlink(missing_ok=True)


def test_shared_widget_renders_order_and_product_payloads(tmp_path: Path) -> None:
    entry = tmp_path / "render_shared_widget.tsx"
    css_types = tmp_path / "css-modules.d.ts"
    bootstrap = tmp_path / "run_render_shared_widget.cjs"
    tsconfig = tmp_path / "tsconfig.shared-widget.json"
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
import { ChatbotWidget } from "@shared-chatbot/ChatbotWidget";

declare const process: {
  stdout: {
    write: (chunk: string) => void;
  };
};

const markup = renderToStaticMarkup(
  <ChatbotWidget
    messages={[
      { type: "text", role: "bot", text: "안녕하세요. MOYEO 챗봇입니다." },
      { type: "order_list", message: "최근 주문 목록입니다.", orders: [] },
      {
        type: "product_list",
        message: "추천 상품",
        products: [{ id: 1, name: "테스트 상품", price: 12000 }],
      },
    ]}
  />
);

process.stdout.write(markup);
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

    try:
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

        emitted = next(out_dir.rglob("render_shared_widget.js"))
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
        assert "안녕하세요. MOYEO 챗봇입니다." in run_result.stdout
        assert "최근 주문 목록입니다." in run_result.stdout
        assert "추천 상품" in run_result.stdout
        assert "테스트 상품" in run_result.stdout
        assert "/products/1.jpg" not in run_result.stdout
    finally:
        if alias_root.exists():
            (alias_root / "ChatbotWidget.js").unlink(missing_ok=True)


def test_shared_widget_order_cs_profile_hides_purchase_controls(tmp_path: Path) -> None:
    output = _run_shared_widget_typescript(
        tmp_path,
        entry_name="render_shared_widget_order_cs.tsx",
        bootstrap_name="run_render_shared_widget_order_cs.cjs",
        tsconfig_name="tsconfig.shared-widget-order-cs.json",
        source="""
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChatbotWidget } from "@shared-chatbot/ChatbotWidget";

declare const process: {
  stdout: {
    write: (chunk: string) => void;
  };
};

const markup = renderToStaticMarkup(
  React.createElement(ChatbotWidget as any, {
    capabilities: ["orders_view", "orders_cancel"],
    messages: [
      {
        type: "product_list",
        message: "추천 상품",
        products: [{ id: 1, name: "테스트 상품", price: 12000 }],
      },
    ],
  }),
);

process.stdout.write(JSON.stringify({ markup }));
        """,
    )

    payload = json.loads(output)
    assert "장바구니" not in payload["markup"]
    assert "바로 구매" not in payload["markup"]


def test_shared_widget_preserves_child_state_across_cloned_message_rerenders(tmp_path: Path) -> None:
    output = _run_shared_widget_typescript(
        tmp_path,
        entry_name="render_shared_widget_cloned_messages.tsx",
        bootstrap_name="run_render_shared_widget_cloned_messages.cjs",
        tsconfig_name="tsconfig.shared-widget-cloned-messages.json",
        source="""
import React from "react";
import { createRoot } from "react-dom/client";
import { ChatbotWidget } from "@shared-chatbot/ChatbotWidget";

declare const process: {
  stdout: {
    write: (chunk: string) => void;
  };
  exit: (code?: number) => void;
};

class NodeBase {
  nodeType: number;
  ownerDocument: DocumentNode | null;
  parentNode: NodeBase | null;
  childNodes: NodeBase[];
  private listeners: Record<string, Array<(...args: unknown[]) => void>>;

  constructor(nodeType: number, ownerDocument: DocumentNode | null) {
    this.nodeType = nodeType;
    this.ownerDocument = ownerDocument;
    this.parentNode = null;
    this.childNodes = [];
    this.listeners = {};
  }

  appendChild(child: NodeBase) {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  insertBefore(child: NodeBase, before: NodeBase | null) {
    child.parentNode = this;
    const index = before ? this.childNodes.indexOf(before) : -1;
    if (index === -1) {
      this.childNodes.push(child);
    } else {
      this.childNodes.splice(index, 0, child);
    }
    return child;
  }

  removeChild(child: NodeBase) {
    const index = this.childNodes.indexOf(child);
    if (index !== -1) {
      this.childNodes.splice(index, 1);
      child.parentNode = null;
    }
    return child;
  }

  addEventListener(type: string, listener: (...args: unknown[]) => void) {
    (this.listeners[type] ||= []).push(listener);
  }

  removeEventListener(type: string, listener: (...args: unknown[]) => void) {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== listener);
  }

  get firstChild() {
    return this.childNodes[0] || null;
  }

  get textContent(): string {
    return this.childNodes.map((child) => child.textContent).join("");
  }

  set textContent(value: string) {
    this.childNodes = [new TextNode(String(value), this.ownerDocument)];
  }
}

class ElementNode extends NodeBase {
  tagName: string;
  nodeName: string;
  style: Record<string, string>;
  attributes: Record<string, string>;
  namespaceURI: string;

  constructor(tagName: string, ownerDocument: DocumentNode) {
    super(1, ownerDocument);
    this.tagName = tagName.toUpperCase();
    this.nodeName = this.tagName;
    this.style = {};
    this.attributes = {};
    this.namespaceURI = "http://www.w3.org/1999/xhtml";
  }

  setAttribute(name: string, value: string) {
    this.attributes[name] = String(value);
  }

  removeAttribute(name: string) {
    delete this.attributes[name];
  }
}

class TextNode extends NodeBase {
  nodeValue: string;

  constructor(text: string, ownerDocument: DocumentNode | null) {
    super(3, ownerDocument);
    this.nodeValue = text;
  }

  get textContent(): string {
    return this.nodeValue;
  }

  set textContent(value: string) {
    this.nodeValue = String(value);
  }
}

class DocumentNode extends NodeBase {
  defaultView: WindowShape | null;
  documentElement: ElementNode;
  body: ElementNode;
  activeElement: ElementNode;

  constructor() {
    super(9, null);
    this.ownerDocument = this;
    this.defaultView = null;
    this.documentElement = new ElementNode("html", this);
    this.body = new ElementNode("body", this);
    this.activeElement = this.body;
    this.appendChild(this.documentElement);
    this.documentElement.appendChild(this.body);
  }

  createElement(tag: string) {
    return new ElementNode(tag, this);
  }

  createTextNode(text: string) {
    return new TextNode(text, this);
  }
}

type WindowShape = {
  document: DocumentNode;
  navigator: { userAgent: string };
  HTMLElement: typeof ElementNode;
  HTMLIFrameElement: typeof ElementNode;
  SVGElement: typeof ElementNode;
  Element: typeof ElementNode;
  Node: typeof NodeBase;
  Text: typeof TextNode;
};

const documentNode = new DocumentNode();
const windowNode: WindowShape = {
  document: documentNode,
  navigator: { userAgent: "node" },
  HTMLElement: ElementNode,
  HTMLIFrameElement: class HTMLIFrameElement extends ElementNode {},
  SVGElement: ElementNode,
  Element: ElementNode,
  Node: NodeBase,
  Text: TextNode,
};

documentNode.defaultView = windowNode;

globalThis.document = documentNode as unknown as Document;
globalThis.window = windowNode as unknown as Window & typeof globalThis;
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: windowNode.navigator,
});
globalThis.HTMLElement = windowNode.HTMLElement as unknown as typeof HTMLElement;
globalThis.HTMLIFrameElement = windowNode.HTMLIFrameElement as unknown as typeof HTMLIFrameElement;
globalThis.Element = windowNode.Element as unknown as typeof Element;
globalThis.Node = windowNode.Node as unknown as typeof Node;
globalThis.Text = windowNode.Text as unknown as typeof Text;

let mountCount = 0;

function ProductSelectionProbe({ name }: { name: string }) {
  const [selection] = React.useState(() => {
    mountCount += 1;
    return `${name}-selection-${mountCount}`;
  });

  return <div>{selection}</div>;
}

const baseMessages = [
  {
    type: "product_list",
    message: "추천 상품",
    products: [{ id: 1, name: "테스트 상품", price: 12000 }],
  },
];

const clonedMessages = baseMessages.map((message) => ({
  ...message,
  products: message.products.map((product) => ({ ...product })),
}));

const container = documentNode.createElement("div");
documentNode.body.appendChild(container);
const root = createRoot(container as unknown as Element);

function render(messages: typeof baseMessages) {
  root.render(
    <ChatbotWidget
      messages={messages}
      renderProductList={(message) => <ProductSelectionProbe name={message.products[0].name} />}
    />,
  );
}

render(baseMessages);

setTimeout(() => {
  const firstText = container.textContent;
  render(clonedMessages);

  setTimeout(() => {
        process.stdout.write(
          JSON.stringify({
            firstText,
            secondText: container.textContent,
            selection_preserved: mountCount === 1,
            mountCount,
          }),
        );
  }, 0);
}, 0);
        """,
    )

    result = json.loads(output)
    assert result["selection_preserved"] is True


def test_shared_widget_source_avoids_site_specific_fallbacks_and_index_keys() -> None:
    product_list_source = (
        REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "ProductListUI.tsx"
    ).read_text(encoding="utf-8")
    chatbot_widget_source = (
        REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "ChatbotWidget.tsx"
    ).read_text(encoding="utf-8")

    assert "/products/${product.id}.jpg" not in product_list_source
    assert "classNames?.primary" in product_list_source
    assert "onClick={() => onCloseSizeModal?.()}" in product_list_source
    assert "event.stopPropagation()" in product_list_source
    assert "key={`order-${index}`}" not in chatbot_widget_source
    assert "key={`product-${index}`}" not in chatbot_widget_source
    assert "key={`text-${index}`}" not in chatbot_widget_source
    assert "key={`fallback-${index}`}" not in chatbot_widget_source


def test_next_config_uses_shared_source_of_truth() -> None:
    shared_source = (REPO_ROOT / "ecommerce" / "frontend" / "next.config.shared.js").read_text(
        encoding="utf-8"
    )
    ts_source = (REPO_ROOT / "ecommerce" / "frontend" / "next.config.ts").read_text(
        encoding="utf-8"
    )
    js_source = (REPO_ROOT / "ecommerce" / "frontend" / "next.config.js").read_text(
        encoding="utf-8"
    )

    assert "externalDir: true" in shared_source
    assert "NEXT_PUBLIC_API_URL" in shared_source
    assert "./next.config.shared.js" in ts_source
    assert "./next.config.shared.js" in js_source
