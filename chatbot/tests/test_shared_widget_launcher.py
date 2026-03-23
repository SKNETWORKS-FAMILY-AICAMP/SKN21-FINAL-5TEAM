from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLING_ROOT = REPO_ROOT if (REPO_ROOT / "node_modules" / ".bin" / "tsc").exists() else REPO_ROOT.parents[1]
FRONTEND_ROOT = REPO_ROOT / "ecommerce" / "frontend"
TSC = TOOLING_ROOT / "node_modules" / ".bin" / "tsc"


def test_chatbot_fab_renders_floating_launcher_shell(tmp_path: Path) -> None:
    entry = tmp_path / "render_shared_widget_launcher.tsx"
    css_types = tmp_path / "css-modules.d.ts"
    bootstrap = tmp_path / "run_render_shared_widget_launcher.cjs"
    tsconfig = tmp_path / "tsconfig.shared-widget-launcher.json"
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
    entry.write_text(
        """
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChatbotFab } from "@shared-chatbot/index";

declare const process: {
  stdout: {
    write: (chunk: string) => void;
  };
};

const markup = renderToStaticMarkup(<ChatbotFab isLoggedIn={true} />);
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
            '    "types": ["node", "react", "react-dom"],\n'
            f'    "outDir": "{out_dir}",\n'
            f'    "baseUrl": "{FRONTEND_ROOT}",\n'
            '    "paths": {\n'
            f'      "@shared-chatbot/*": ["{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "*"}"],\n'
            f'      "@skn/shared-chatbot/*": ["{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "*"}"],\n'
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

    emitted = next(out_dir.rglob("render_shared_widget_launcher.js"))
    shared_index_js = next(out_dir.rglob("index.js"))
    shared_widget_js = next(out_dir.rglob("ChatbotWidget.js"))
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
    assert 'aria-hidden="true"' in run_result.stdout
    assert 'data-launcher-mode="floating"' in run_result.stdout
    assert 'aria-label="챗봇 열기"' in run_result.stdout


def _build_shared_widget_bundle(tmp_path: Path, entry_source: str) -> tuple[Path, Path]:
    entry = tmp_path / "render_shared_widget_launcher.tsx"
    css_types = tmp_path / "css-modules.d.ts"
    tsconfig = tmp_path / "tsconfig.shared-widget-launcher.json"
    out_dir = tmp_path / "dist"
    alias_root = tmp_path / "alias-node-modules" / "@shared-chatbot"

    css_types.write_text(
        "declare module '*.module.css' {\n"
        "  const classes: Record<string, string>;\n"
        "  export default classes;\n"
        "}\n",
        encoding="utf-8",
    )
    entry.write_text(entry_source, encoding="utf-8")
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
            f'      "@skn/shared-chatbot/*": ["{REPO_ROOT / "chatbot" / "frontend" / "shared_widget" / "*"}"],\n'
            f'      "react": ["{TOOLING_ROOT / "node_modules" / "react"}"],\n'
            f'      "react-dom/client": ["{TOOLING_ROOT / "node_modules" / "react-dom" / "client"}"],\n'
            f'      "react/jsx-runtime": ["{TOOLING_ROOT / "node_modules" / "react" / "jsx-runtime"}"]\n'
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

    emitted = next(out_dir.rglob("render_shared_widget_launcher.js"))
    shared_widget_entry_js = next(out_dir.rglob("widget-entry.js"))
    shared_web_component_js = next(out_dir.rglob("web-component.js"))
    shared_widget_js = next(out_dir.rglob("ChatbotWidget.js"))
    shared_widget_alias_root = tmp_path / "alias-node-modules" / "@skn" / "shared-chatbot"
    for css_name in (
        "chatbot-widget.module.css",
        "chatbotfab.module.css",
        "productlist.module.css",
        "reviewform.module.css",
        "usedsaleform.module.css",
    ):
        (shared_widget_js.parent / css_name).write_text("", encoding="utf-8")
    alias_root.mkdir(parents=True, exist_ok=True)
    shared_widget_alias_root.mkdir(parents=True, exist_ok=True)
    (alias_root / "widget-entry.js").write_text(
        f'module.exports = require("{shared_widget_entry_js}");\n',
        encoding="utf-8",
    )
    (shared_widget_alias_root / "ChatbotWidget.js").write_text(
        f'module.exports = require("{shared_widget_js}");\n',
        encoding="utf-8",
    )

    return emitted, shared_web_component_js


def _run_shared_widget_bundle(bootstrap: Path, emitted: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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


def test_shared_widget_web_component_registers_shadow_root_and_prefers_attributes(tmp_path: Path) -> None:
    emitted, web_component_js = _build_shared_widget_bundle(
        tmp_path,
        dedent(
            """
            import "@shared-chatbot/widget-entry";
            """
        ).strip()
        + "\n",
    )
    bootstrap = tmp_path / "run_render_shared_widget_launcher.cjs"
    bootstrap.write_text(
        dedent(
            """
            require.extensions[".css"] = (module) => {
              module.exports = {};
            };
            const Module = require("module");
            const originalLoad = Module._load;
            const renderCalls = [];
            const unmountCalls = [];
            const reactStub = {
              createElement(type, props, ...children) {
                return {
                  type,
                  props: {
                    ...(props || {}),
                    children: children.length <= 1 ? children[0] : children,
                  },
                };
              },
            };
            const jsxRuntimeStub = {
              jsx(type, props) {
                return { type, props: props || {} };
              },
              jsxs(type, props) {
                return { type, props: props || {} };
              },
              Fragment: Symbol.for("react.fragment"),
            };
            class HTMLElementStub {
              constructor() {
                this.attributes = new Map();
                this.shadowRoot = null;
              }
              setAttribute(name, value) {
                this.attributes.set(name, String(value));
              }
              getAttribute(name) {
                return this.attributes.has(name) ? this.attributes.get(name) : null;
              }
              hasAttribute(name) {
                return this.attributes.has(name);
              }
              attachShadow(init) {
                const shadowRoot = {
                  mode: init.mode,
                  host: this,
                  children: [],
                  appendChild(node) {
                    this.children.push(node);
                    return node;
                  },
                };
                this.shadowRoot = shadowRoot;
                return shadowRoot;
              }
            }
            const customElementsRegistry = new Map();
            globalThis.HTMLElement = HTMLElementStub;
            globalThis.customElements = {
              define(name, value) {
                customElementsRegistry.set(name, value);
              },
              get(name) {
                return customElementsRegistry.get(name);
              },
            };
            globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__ = {
              chatbotServerBaseUrl: "https://global.example.com/base/",
              authBootstrapPath: "/global/auth-token",
              widgetBundlePath: "/global/widget.js",
              widgetElementTag: "ignored-host-tag",
              mountMode: "floating_launcher",
            };
            Module._load = function(request, parent, isMain) {
              if (request === "react") {
                return reactStub;
              }
              if (request === "react/jsx-runtime") {
                return jsxRuntimeStub;
              }
              if (request === "react-dom/client") {
                return {
                  createRoot(container) {
                    const record = {
                      container,
                      render(node) {
                        renderCalls.push({ container, node });
                      },
                      unmount() {
                        unmountCalls.push(container);
                      },
                    };
                    return record;
                  },
                };
              }
              return originalLoad.apply(this, arguments);
            };
                require("__EMITTED__");
                const WidgetElement = globalThis.customElements.get("order-cs-widget");
                const element = new WidgetElement();
                element.setAttribute("chatbot-server-base-url", "https://attr.example.com/api/");
                element.setAttribute("auth-bootstrap-path", "/attr/auth-token");
                element.setAttribute("widget-bundle-path", "/attr/widget.js");
                const { resolveOrderCsWidgetHostContract } = require("__WEB_COMPONENT__");
                const resolvedContract = resolveOrderCsWidgetHostContract({
                  "chatbot-server-base-url": "https://attr.example.com/api/",
                  "auth-bootstrap-path": "/attr/auth-token",
                  "widget-bundle-path": "/attr/widget.js",
                });
                element.connectedCallback();
                const renderNode = renderCalls[0]?.node || null;
                const summary = {
                  registered: Boolean(WidgetElement),
                  shadowAttached: Boolean(element.shadowRoot),
                  shadowMode: element.shadowRoot?.mode ?? null,
                  renderedComponent: renderNode?.type?.name ?? null,
                  host: renderNode?.props?.host ?? null,
                  resolvedContract,
                };
                process.stdout.write(JSON.stringify(summary));
                """
            ).strip().replace("__EMITTED__", str(emitted)).replace("__WEB_COMPONENT__", str(web_component_js)),
            encoding="utf-8",
        )

    run_result = _run_shared_widget_bundle(bootstrap, emitted, tmp_path)
    assert run_result.returncode == 0, run_result.stderr
    summary = __import__("json").loads(run_result.stdout)
    assert summary["registered"] is True
    assert summary["shadowAttached"] is True
    assert summary["shadowMode"] == "open"
    assert summary["renderedComponent"] == "ChatbotFab"
    assert summary["host"] == {
        "authBootstrapPath": "/attr/auth-token",
        "chatbotApiBase": "https://attr.example.com/api",
        "chatPath": "/api/chat",
        "streamPath": "/api/v1/chat/stream",
    }
    assert summary["resolvedContract"] == {
        "chatbotServerBaseUrl": "https://attr.example.com/api",
        "authBootstrapPath": "/attr/auth-token",
        "widgetBundlePath": "/attr/widget.js",
        "widgetElementTag": "order-cs-widget",
        "mountMode": "floating_launcher",
    }


def test_shared_widget_web_component_uses_global_contract_without_attributes(tmp_path: Path) -> None:
    emitted, _web_component_js = _build_shared_widget_bundle(
        tmp_path,
        dedent(
            """
            import "@shared-chatbot/widget-entry";
            """
        ).strip()
        + "\n",
    )
    bootstrap = tmp_path / "run_render_shared_widget_launcher.cjs"
    bootstrap.write_text(
        dedent(
            """
            require.extensions[".css"] = (module) => {
              module.exports = {};
            };
            const Module = require("module");
            const originalLoad = Module._load;
            const renderCalls = [];
            let unmountCount = 0;
            class HTMLElementStub {
              constructor() {
                this.attributes = new Map();
                this.shadowRoot = null;
              }
              setAttribute(name, value) {
                this.attributes.set(name, String(value));
              }
              getAttribute(name) {
                return this.attributes.has(name) ? this.attributes.get(name) : null;
              }
              hasAttribute(name) {
                return this.attributes.has(name);
              }
              attachShadow(init) {
                const shadowRoot = {
                  mode: init.mode,
                  host: this,
                  children: [],
                  appendChild(node) {
                    this.children.push(node);
                    return node;
                  },
                };
                this.shadowRoot = shadowRoot;
                return shadowRoot;
              }
            }
            const customElementsRegistry = new Map();
            globalThis.HTMLElement = HTMLElementStub;
            globalThis.customElements = {
              define(name, value) {
                customElementsRegistry.set(name, value);
              },
              get(name) {
                return customElementsRegistry.get(name);
              },
            };
            globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__ = {
              chatbotServerBaseUrl: "https://global.example.com/base/",
              authBootstrapPath: "/global/auth-token",
              widgetBundlePath: "/global/widget.js",
              widgetElementTag: "host-tag",
              mountMode: "floating_launcher",
            };
            Module._load = function(request, parent, isMain) {
              if (request === "react") {
                return {
                  createElement(type, props, ...children) {
                    return {
                      type,
                      props: {
                        ...(props || {}),
                        children: children.length <= 1 ? children[0] : children,
                      },
                    };
                  },
                };
              }
              if (request === "react/jsx-runtime") {
                return {
                  jsx(type, props) {
                    return { type, props: props || {} };
                  },
                  jsxs(type, props) {
                    return { type, props: props || {} };
                  },
                  Fragment: Symbol.for("react.fragment"),
                };
              }
              if (request === "react-dom/client") {
                return {
                  createRoot(container) {
                    return {
                      render(node) {
                        renderCalls.push({ container, node });
                      },
                      unmount() {
                        unmountCount += 1;
                      },
                    };
                  },
                };
              }
              return originalLoad.apply(this, arguments);
            };
            require("__EMITTED__");
            const WidgetElement = globalThis.customElements.get("order-cs-widget");
            const element = new WidgetElement();
            element.connectedCallback();
            const { resolveOrderCsWidgetHostContract } = require("__WEB_COMPONENT__");
            const resolvedContract = resolveOrderCsWidgetHostContract();
            const renderNode = renderCalls[0]?.node || null;
            process.stdout.write(JSON.stringify({
              renderedComponent: renderNode?.type?.name ?? null,
              host: renderNode?.props?.host ?? null,
              resolvedContract,
              unmountCount,
            }));
            """
        ).strip().replace("__EMITTED__", str(emitted)).replace("__WEB_COMPONENT__", str(_web_component_js)),
        encoding="utf-8",
    )

    run_result = _run_shared_widget_bundle(bootstrap, emitted, tmp_path)
    assert run_result.returncode == 0, run_result.stderr
    summary = __import__("json").loads(run_result.stdout)
    assert summary["renderedComponent"] == "ChatbotFab"
    assert summary["host"] == {
        "authBootstrapPath": "/global/auth-token",
        "chatbotApiBase": "https://global.example.com/base",
        "chatPath": "/api/chat",
        "streamPath": "/api/v1/chat/stream",
    }
    assert summary["resolvedContract"] == {
        "chatbotServerBaseUrl": "https://global.example.com/base",
        "authBootstrapPath": "/global/auth-token",
        "widgetBundlePath": "/global/widget.js",
        "widgetElementTag": "order-cs-widget",
        "mountMode": "floating_launcher",
    }
    assert summary["unmountCount"] == 0


def test_shared_widget_widget_entry_imports_without_custom_elements(tmp_path: Path) -> None:
    emitted, _web_component_js = _build_shared_widget_bundle(
        tmp_path,
        dedent(
            """
            import "@shared-chatbot/widget-entry";
            """
        ).strip()
        + "\n",
    )
    bootstrap = tmp_path / "run_render_shared_widget_launcher.cjs"
    bootstrap.write_text(
        dedent(
            """
            require.extensions[".css"] = (module) => {
              module.exports = {};
            };
            const Module = require("module");
            const originalLoad = Module._load;
            Module._load = function(request, parent, isMain) {
              if (request === "react") {
                return {
                  createElement(type, props, ...children) {
                    return {
                      type,
                      props: {
                        ...(props || {}),
                        children: children.length <= 1 ? children[0] : children,
                      },
                    };
                  },
                };
              }
              if (request === "react/jsx-runtime") {
                return {
                  jsx(type, props) {
                    return { type, props: props || {} };
                  },
                  jsxs(type, props) {
                    return { type, props: props || {} };
                  },
                  Fragment: Symbol.for("react.fragment"),
                };
              }
              if (request === "react-dom/client") {
                return {
                  createRoot() {
                    return {
                      render() {},
                      unmount() {},
                    };
                  },
                };
              }
              return originalLoad.apply(this, arguments);
            };
            globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__ = {
              chatbotServerBaseUrl: "https://global.example.com/base/",
              widgetElementTag: "host-tag",
            };
            require("__EMITTED__");
            process.stdout.write(JSON.stringify(globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__));
            """
        ).strip().replace("__EMITTED__", str(emitted)),
        encoding="utf-8",
    )

    run_result = _run_shared_widget_bundle(bootstrap, emitted, tmp_path)
    assert run_result.returncode == 0, run_result.stderr
    merged_contract = __import__("json").loads(run_result.stdout)
    assert merged_contract == {
        "chatbotServerBaseUrl": "https://global.example.com/base/",
        "authBootstrapPath": "/api/chat/auth-token",
        "widgetBundlePath": "/widget.js",
        "widgetElementTag": "order-cs-widget",
        "mountMode": "floating_launcher",
    }


def test_shared_widget_web_component_unmounts_on_disconnect(tmp_path: Path) -> None:
    emitted, _web_component_js = _build_shared_widget_bundle(
        tmp_path,
        dedent(
            """
            import "@shared-chatbot/widget-entry";
            """
        ).strip()
        + "\n",
    )
    bootstrap = tmp_path / "run_render_shared_widget_launcher.cjs"
    bootstrap.write_text(
        dedent(
            """
            require.extensions[".css"] = (module) => {
              module.exports = {};
            };
            const Module = require("module");
            const originalLoad = Module._load;
            let unmountCount = 0;
            class HTMLElementStub {
              constructor() {
                this.attributes = new Map();
                this.shadowRoot = null;
              }
              setAttribute(name, value) {
                this.attributes.set(name, String(value));
              }
              getAttribute(name) {
                return this.attributes.has(name) ? this.attributes.get(name) : null;
              }
              hasAttribute(name) {
                return this.attributes.has(name);
              }
              attachShadow(init) {
                const shadowRoot = {
                  mode: init.mode,
                  host: this,
                  children: [],
                  appendChild(node) {
                    this.children.push(node);
                    return node;
                  },
                };
                this.shadowRoot = shadowRoot;
                return shadowRoot;
              }
            }
            const customElementsRegistry = new Map();
            globalThis.HTMLElement = HTMLElementStub;
            globalThis.customElements = {
              define(name, value) {
                customElementsRegistry.set(name, value);
              },
              get(name) {
                return customElementsRegistry.get(name);
              },
            };
            globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__ = {
              chatbotServerBaseUrl: "",
              authBootstrapPath: "/global/auth-token",
              widgetBundlePath: "/global/widget.js",
              widgetElementTag: "order-cs-widget",
              mountMode: "floating_launcher",
            };
            Module._load = function(request, parent, isMain) {
              if (request === "react") {
                return {
                  createElement(type, props, ...children) {
                    return {
                      type,
                      props: {
                        ...(props || {}),
                        children: children.length <= 1 ? children[0] : children,
                      },
                    };
                  },
                };
              }
              if (request === "react/jsx-runtime") {
                return {
                  jsx(type, props) {
                    return { type, props: props || {} };
                  },
                  jsxs(type, props) {
                    return { type, props: props || {} };
                  },
                  Fragment: Symbol.for("react.fragment"),
                };
              }
              if (request === "react-dom/client") {
                return {
                  createRoot() {
                    return {
                      render() {},
                      unmount() {
                        unmountCount += 1;
                      },
                    };
                  },
                };
              }
              return originalLoad.apply(this, arguments);
            };
            require("__EMITTED__");
            const WidgetElement = globalThis.customElements.get("order-cs-widget");
            const element = new WidgetElement();
            element.connectedCallback();
            element.disconnectedCallback();
            process.stdout.write(String(unmountCount));
            """
        ).strip().replace("__EMITTED__", str(emitted)),
        encoding="utf-8",
    )

    run_result = _run_shared_widget_bundle(bootstrap, emitted, tmp_path)
    assert run_result.returncode == 0, run_result.stderr
    assert run_result.stdout == "1"
