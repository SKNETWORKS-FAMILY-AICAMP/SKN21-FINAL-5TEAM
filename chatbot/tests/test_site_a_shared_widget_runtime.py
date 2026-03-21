from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "ecommerce" / "frontend"
TSC = FRONTEND_ROOT / "node_modules" / ".bin" / "tsc"


def test_site_a_shared_widget_runtime_flow(tmp_path: Path) -> None:
    entry = tmp_path / "run_site_a_shared_widget_runtime.tsx"
    css_types = tmp_path / "css-modules.d.ts"
    bootstrap = tmp_path / "run_site_a_shared_widget_runtime.cjs"
    tsconfig = tmp_path / "tsconfig.site-a-shared-widget.json"
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
            site_id: "site-a",
            access_token: "food-bridge-token",
          }),
      };
    }

    if (url === "http://localhost:9000/api/chat") {
      return {
        ok: true,
        json: async () => ({
          answer: "추천 메뉴를 찾았어요.",
          conversation_id: "food-conv-001",
          completed_tasks: [],
          ui_action_required: "show_product_list",
          awaiting_interrupt: false,
          interrupts: [],
          state: {
            search_context: {
              retrieved_products: [{ id: 7, name: "파스타", price: 15000 }],
            },
          },
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
    message: "추천 상품 보여줘",
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

        emitted = next(out_dir.rglob("run_site_a_shared_widget_runtime.js"))
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
        assert payload["siteId"] == "site-a"
        assert payload["calls"][1]["url"] == "http://localhost:9000/api/chat"
        request_body = json.loads(payload["calls"][1]["options"]["body"])
        assert request_body["site_id"] == "site-a"
        assert request_body["access_token"] == "food-bridge-token"
        assert "추천 메뉴를 찾았어요." in payload["markup"]
        assert "추천 상품" in payload["markup"]
        assert "파스타" in payload["markup"]
    finally:
        (alias_root / "ChatbotWidget.js").unlink(missing_ok=True)
