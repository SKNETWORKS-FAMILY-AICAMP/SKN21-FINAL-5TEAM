#!/usr/bin/env python3
"""
JSONL chatbot audit log -> HTML report generator.

Usage:
  python scripts/chatbot_log_to_html.py \
    --input logs/chatbot/conv_xxx.jsonl \
    --output logs/chatbot/conv_xxx.html
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return html.escape(json.dumps(value, ensure_ascii=False, indent=2))
    return html.escape(str(value))


def _payload_summary(item: Dict[str, Any]) -> str:
    parts: List[str] = []
    input_payload = item.get("input")
    output_payload = item.get("output")
    usage_payload = item.get("usage")

    if isinstance(input_payload, dict):
        msg = input_payload.get("messages")
        if isinstance(msg, dict) and msg.get("_kind") == "messages_preview":
            parts.append(f"messages={msg.get('count', 0)}")
        elif isinstance(msg, list):
            parts.append(f"messages={len(msg)}")

        question = input_payload.get("question")
        if isinstance(question, str) and question.strip():
            parts.append(f"q={_safe(question[:40])}")

    if isinstance(output_payload, dict):
        generation = output_payload.get("generation")
        if isinstance(generation, str) and generation.strip():
            parts.append(f"gen={_safe(generation[:40])}")

    if isinstance(usage_payload, dict):
        total_tokens = usage_payload.get("total_tokens")
        if total_tokens:
            parts.append(f"tokens={_safe(total_tokens)}")

    if not parts:
        if item.get("event") == "start":
            return "start event"
        if item.get("event") == "end":
            return "end event"
        return "payload available"

    return " | ".join(parts)


def _load_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    errors.append(f"Line {i}: not a JSON object")
            except Exception as e:
                errors.append(f"Line {i}: {e}")

    return rows, errors


def _timeline_table(title: str, items: List[Dict[str, Any]], key_name: str) -> str:
    if not items:
        return f"<h4>{html.escape(title)}</h4><p class='muted'>No data</p>"

    trs: List[str] = []
    for item in items:
        payload_detail = (
            "<details>"
            "<summary>view payload</summary>"
            "<div class='payload-grid'>"
            f"<div><b>input</b><pre>{_safe(item.get('input'))}</pre></div>"
            f"<div><b>output</b><pre>{_safe(item.get('output'))}</pre></div>"
            f"<div><b>usage</b><pre>{_safe(item.get('usage'))}</pre></div>"
            "</div>"
            "</details>"
        )
        trs.append(
            "<tr>"
            f"<td>{_safe(item.get('event'))}</td>"
            f"<td>{_safe(item.get(key_name))}</td>"
            f"<td>{_safe(item.get('at'))}</td>"
            f"<td>{_safe(item.get('duration_ms'))}</td>"
            f"<td><div class='payload-summary'>{_payload_summary(item)}</div>{payload_detail}</td>"
            "</tr>"
        )

    return (
        f"<h4>{html.escape(title)}</h4>"
        "<div class='table-wrap'>"
        "<table>"
        "<thead><tr><th>event</th><th>name</th><th>at</th><th>duration_ms</th><th>payload</th></tr></thead>"
        f"<tbody>{''.join(trs)}</tbody>"
        "</table>"
        "</div>"
    )


def _build_turn_card(turn: Dict[str, Any], index: int) -> str:
    metrics = turn.get("metrics", {}) if isinstance(turn.get("metrics"), dict) else {}
    token_usage = metrics.get("token_usage", {}) if isinstance(metrics.get("token_usage"), dict) else {}
    timeline = turn.get("timeline", {}) if isinstance(turn.get("timeline"), dict) else {}

    header = (
        "<div class='turn-header'>"
        f"<h3>Turn {index}</h3>"
        f"<span class='badge status-{_safe(turn.get('status')).lower()}'>{_safe(turn.get('status'))}</span>"
        "</div>"
        "<div class='kv-grid'>"
        f"<div><b>turn_id</b><br>{_safe(turn.get('turn_id'))}</div>"
        f"<div><b>started_at</b><br>{_safe(turn.get('started_at'))}</div>"
        f"<div><b>finished_at</b><br>{_safe(turn.get('finished_at'))}</div>"
        f"<div><b>duration_ms</b><br>{_safe(metrics.get('duration_ms'))}</div>"
        f"<div><b>input_tokens</b><br>{_safe(token_usage.get('input_tokens'))}</div>"
        f"<div><b>output_tokens</b><br>{_safe(token_usage.get('output_tokens'))}</div>"
        f"<div><b>total_tokens</b><br>{_safe(token_usage.get('total_tokens'))}</div>"
        f"<div><b>provider/model</b><br>{_safe(turn.get('provider'))} / {_safe(turn.get('model'))}</div>"
        "</div>"
    )

    user_message = turn.get("input", {}).get("user_message") if isinstance(turn.get("input"), dict) else None
    output_generation = turn.get("output", {}).get("generation") if isinstance(turn.get("output"), dict) else None
    state_changes = turn.get("state_changes", []) if isinstance(turn.get("state_changes"), list) else []
    errors = turn.get("errors", []) if isinstance(turn.get("errors"), list) else []

    state_changes_html = "<p class='muted'>No state changes</p>"
    if state_changes:
        chunks = []
        for c_idx, change in enumerate(state_changes, start=1):
            chunks.append(
                f"<details><summary>State Change {c_idx} ({_safe(change.get('at'))})</summary>"
                f"<pre>{_safe(change.get('changes'))}</pre></details>"
            )
        state_changes_html = "".join(chunks)

    errors_html = "<p class='muted'>No errors</p>"
    if errors:
        errors_html = "".join(
            f"<div class='error-item'><b>{_safe(e.get('where'))}</b>: {_safe(e.get('message'))}</div>" for e in errors
        )

    return (
        "<section class='turn-card'>"
        f"{header}"
        "<div class='io-grid'>"
        f"<div><h4>User Input</h4><pre>{_safe(user_message)}</pre></div>"
        f"<div><h4>Assistant Output</h4><pre>{_safe(output_generation)}</pre></div>"
        "</div>"
        "<details><summary>Input State Summary</summary>"
        f"<pre>{_safe(turn.get('input', {}).get('state_summary') if isinstance(turn.get('input'), dict) else None)}</pre>"
        "</details>"
        "<details><summary>Output State Summary</summary>"
        f"<pre>{_safe(turn.get('output', {}).get('state_summary') if isinstance(turn.get('output'), dict) else None)}</pre>"
        "</details>"
        f"{_timeline_table('Nodes', timeline.get('nodes', []) if isinstance(timeline.get('nodes'), list) else [], 'node')}"
        f"{_timeline_table('Tools', timeline.get('tools', []) if isinstance(timeline.get('tools'), list) else [], 'tool')}"
        f"{_timeline_table('Models', timeline.get('models', []) if isinstance(timeline.get('models'), list) else [], 'model')}"
        "<h4>State Changes</h4>"
        f"{state_changes_html}"
        "<h4>Errors</h4>"
        f"{errors_html}"
        "<details><summary>Raw Turn JSON</summary>"
        f"<pre>{_safe(turn)}</pre>"
        "</details>"
        "</section>"
    )


def _build_html(input_file: Path, turns: List[Dict[str, Any]], parse_errors: List[str]) -> str:
    conversation_id = turns[0].get("conversation_id") if turns else "(empty)"

    total_duration = 0
    total_tokens = 0
    for t in turns:
        metrics = t.get("metrics", {}) if isinstance(t.get("metrics"), dict) else {}
        duration = metrics.get("duration_ms") or 0
        tokens = metrics.get("token_usage", {}).get("total_tokens") if isinstance(metrics.get("token_usage"), dict) else 0
        total_duration += int(duration or 0)
        total_tokens += int(tokens or 0)

    turn_cards = "".join(_build_turn_card(t, i) for i, t in enumerate(turns, start=1))

    parse_error_html = ""
    if parse_errors:
        parse_error_html = "".join(f"<li>{_safe(e)}</li>" for e in parse_errors)
        parse_error_html = f"<section class='warn'><h3>Parse Warnings</h3><ul>{parse_error_html}</ul></section>"

    return f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Chatbot Audit Log Viewer</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 24px; background: #f7f8fa; color: #1f2937; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .header {{ background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px 20px; margin-bottom: 16px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .summary .item {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px 12px; }}
    .turn-card {{ background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; margin: 16px 0; }}
    .turn-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
    .badge {{ padding: 4px 8px; border-radius: 8px; font-size: 12px; }}
    .status-success {{ background: #dcfce7; color: #166534; }}
    .status-error {{ background: #fee2e2; color: #991b1b; }}
    .kv-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin-bottom: 12px; }}
    .io-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }}
    @media (max-width: 900px) {{ .io-grid {{ grid-template-columns: 1fr; }} }}
    .table-wrap {{ overflow-x: auto; margin-bottom: 12px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }}
    th {{ background: #f9fafb; text-align: left; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #111827; color: #e5e7eb; padding: 10px; border-radius: 8px; max-height: 240px; overflow: auto; }}
    details {{ margin: 8px 0; }}
    .muted {{ color: #6b7280; }}
    .warn {{ background: #fff7ed; border: 1px solid #fed7aa; border-radius: 10px; padding: 12px; margin: 12px 0; }}
    .error-item {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 8px; margin: 6px 0; }}
    .payload-summary {{ font-size: 12px; color: #334155; margin-bottom: 6px; }}
    .payload-grid {{ display: grid; gap: 8px; margin-top: 8px; }}
  </style>
</head>
<body>
  <div class="container">
    <section class="header">
      <h1>Chatbot Audit Log Viewer</h1>
      <p class="muted">source: {_safe(str(input_file))}</p>
      <div class="summary">
        <div class="item"><b>conversation_id</b><br>{_safe(conversation_id)}</div>
        <div class="item"><b>turns</b><br>{len(turns)}</div>
        <div class="item"><b>total_duration_ms</b><br>{total_duration}</div>
        <div class="item"><b>total_tokens</b><br>{total_tokens}</div>
      </div>
    </section>

    {parse_error_html}
    {turn_cards if turn_cards else '<p>No valid rows found.</p>'}
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render chatbot JSONL audit log to HTML")
    parser.add_argument("--input", required=True, help="Path to JSONL log file")
    parser.add_argument("--output", required=False, help="Path to output HTML file")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_suffix(".html")
    )

    turns, parse_errors = _load_jsonl(input_path)
    html_content = _build_html(input_path, turns, parse_errors)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")

    print(f"[OK] HTML report generated: {output_path}")


if __name__ == "__main__":
    main()
