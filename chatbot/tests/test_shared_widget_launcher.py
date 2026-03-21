from __future__ import annotations

import os
import subprocess
from pathlib import Path


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
