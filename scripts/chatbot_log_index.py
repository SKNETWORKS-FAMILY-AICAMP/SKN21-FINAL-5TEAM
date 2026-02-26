#!/usr/bin/env python3
"""
Generate an index HTML for chatbot audit logs.

Usage:
  python scripts/chatbot_log_index.py \
    --logs-dir logs/chatbot \
    --output logs/chatbot/index.html
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _load_jsonl_head_tail(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], int]:
    first: Optional[Dict[str, Any]] = None
    last: Optional[Dict[str, Any]] = None
    count = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    continue
                if first is None:
                    first = obj
                last = obj
                count += 1
            except Exception:
                continue

    return first, last, count


def _fmt_time(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _relative_link(from_file: Path, target: Path) -> str:
    try:
        rel = target.relative_to(from_file.parent)
    except Exception:
        rel = Path(target.name)
    return rel.as_posix()


def _collect_rows(logs_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for jsonl in sorted(logs_dir.glob("conv_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        first, last, turns = _load_jsonl_head_tail(jsonl)

        conv_id = (first or {}).get("conversation_id") or jsonl.stem
        provider = (last or first or {}).get("provider")
        model = (last or first or {}).get("model")
        status = (last or first or {}).get("status")

        total_duration = 0
        total_tokens = 0
        if turns > 0:
            with jsonl.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if not isinstance(obj, dict):
                            continue
                        metrics = obj.get("metrics", {}) if isinstance(obj.get("metrics"), dict) else {}
                        token_usage = metrics.get("token_usage", {}) if isinstance(metrics.get("token_usage"), dict) else {}
                        total_duration += int(metrics.get("duration_ms") or 0)
                        total_tokens += int(token_usage.get("total_tokens") or 0)
                    except Exception:
                        continue

        html_report = jsonl.with_suffix(".html")
        rows.append(
            {
                "conversation_id": conv_id,
                "jsonl": jsonl,
                "html": html_report if html_report.exists() else None,
                "turns": turns,
                "provider": provider,
                "model": model,
                "status": status,
                "duration_ms": total_duration,
                "tokens": total_tokens,
                "updated_at": _fmt_time(jsonl),
            }
        )

    return rows


def _build_html(rows: List[Dict[str, Any]], output_path: Path, logs_dir: Path) -> str:
    trs: List[str] = []
    for row in rows:
        jsonl_path: Path = row["jsonl"]
        html_path: Optional[Path] = row["html"]

        jsonl_link = _relative_link(output_path, jsonl_path)
        html_link = _relative_link(output_path, html_path) if html_path else ""

        html_cell = (
            f"<a href=\"{_safe(html_link)}\" target=\"_blank\">open report</a>"
            if html_path
            else "<span class='muted'>not generated</span>"
        )

        browser_generate_btn = (
            f"<button onclick=\"generateReportFromJsonl('{_safe(jsonl_link)}')\">generate in page</button>"
        )

        trs.append(
            "<tr>"
            f"<td>{_safe(row['conversation_id'])}</td>"
            f"<td><a href=\"{_safe(jsonl_link)}\" target=\"_blank\">jsonl</a></td>"
            f"<td>{html_cell}</td>"
            f"<td>{browser_generate_btn}</td>"
            f"<td>{_safe(row['turns'])}</td>"
            f"<td>{_safe(row['provider'])}</td>"
            f"<td>{_safe(row['model'])}</td>"
            f"<td>{_safe(row['status'])}</td>"
            f"<td>{_safe(row['duration_ms'])}</td>"
            f"<td>{_safe(row['tokens'])}</td>"
            f"<td>{_safe(row['updated_at'])}</td>"
            "</tr>"
        )

    return f"""
<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Chatbot Log Index</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 24px; background: #f7f8fa; color: #1f2937; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .header {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
    .muted {{ color: #6b7280; }}
    .table-wrap {{ overflow-x: auto; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f9fafb; position: sticky; top: 0; }}
    tr:hover td {{ background: #f9fafb; }}
        button {{ background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 6px 10px; cursor: pointer; font-size: 12px; }}
        button:hover {{ background: #1d4ed8; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
        .actions {{ display: flex; gap: 8px; align-items: center; margin-top: 8px; }}
  </style>
</head>
<body>
  <div class=\"container\">
    <section class=\"header\">
      <h1>Chatbot Log Index</h1>
      <p class=\"muted\">logs directory: {_safe(str(logs_dir))}</p>
      <p class=\"muted\" id=\"totalConversations\">total conversations: {len(rows)}</p>
            <div class=\"actions\">
                <button onclick=\"connectLogsFolder()\">connect logs folder</button>
                <button onclick=\"syncConnectedFolder(true)\">sync & generate/update html</button>
                <button onclick=\"syncConnectedFolder(false)\">refresh only</button>
                <button onclick=\"toggleAutoSync()\" id=\"autoSyncBtn\">auto-sync: off</button>
                <span class=\"muted\" id=\"folderStatus\">실시간 디렉토리 디버깅을 위해 logs/chatbot 폴더를 연결하세요.</span>
            </div>
            <input id=\"folderPicker\" type=\"file\" webkitdirectory directory multiple style=\"display:none\" />
    </section>

    <div class=\"table-wrap\">
      <table>
        <thead>
          <tr>
            <th>conversation_id</th>
            <th>raw log</th>
            <th>html report</th>
            <th>in-page generate</th>
            <th>turns</th>
            <th>provider</th>
            <th>model</th>
            <th>status</th>
            <th>total_duration_ms</th>
            <th>total_tokens</th>
            <th>updated_at</th>
          </tr>
        </thead>
                <tbody id=\"logsTbody\">
                    {''.join(trs) if trs else '<tr><td colspan="11">No log files found.</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>

    <script>
        function esc(v) {{
            if (v === null || v === undefined) return '';
            return String(v)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;');
        }}

        let connectedDirHandle = null;
        let autoSyncTimer = null;
        const jsonlHandleMap = new Map();
        const htmlHandleMap = new Map();

        function parseJsonl(text) {{
            return text
                .split(/\\r?\\n/)
                .map(line => line.trim())
                .filter(Boolean)
                .map(line => {{
                    try {{ return JSON.parse(line); }} catch {{ return null; }}
                }})
                .filter(obj => obj && typeof obj === 'object');
        }}

                function pretty(v) {{
                        if (v === null || v === undefined) return '';
                        if (typeof v === 'object') {{
                                try {{ return JSON.stringify(v, null, 2); }} catch {{ return String(v); }}
                        }}
                        return String(v);
                }}

                function buildTurnCard(turn, idx) {{
            const metrics = turn.metrics || {{}};
            const token = metrics.token_usage || {{}};
            const timeline = turn.timeline || {{}};
            const userMsg = turn.input?.user_message || '';
            const generation = turn.output?.generation || '';

            const renderTable = (title, arr, keyName) => {{
                if (!Array.isArray(arr) || !arr.length) return `<h4>${{title}}</h4><p style="color:#6b7280">No data</p>`;
                const rows = arr.map(item => `
                    <tr>
                        <td>${{esc(item.event)}}</td>
                        <td>${{esc(item[keyName])}}</td>
                        <td>${{esc(item.at)}}</td>
                        <td>${{esc(item.duration_ms)}}</td>
                                                <td>
                                                    <details>
                                                        <summary>view payload</summary>
                                                        <div style="display:grid;gap:8px;margin-top:8px;">
                                                            <div><b>input</b><pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:8px;border-radius:8px;max-height:240px;overflow:auto;">${{esc(pretty(item.input))}}</pre></div>
                                                            <div><b>output</b><pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:8px;border-radius:8px;max-height:240px;overflow:auto;">${{esc(pretty(item.output))}}</pre></div>
                                                            <div><b>usage</b><pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:8px;border-radius:8px;max-height:180px;overflow:auto;">${{esc(pretty(item.usage))}}</pre></div>
                                                        </div>
                                                    </details>
                                                </td>
                    </tr>
                `).join('');
                return `
                    <h4>${{title}}</h4>
                                        <table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
                                                <thead><tr><th>event</th><th>name</th><th>at</th><th>duration_ms</th><th>input/output</th></tr></thead>
                        <tbody>${{rows}}</tbody>
                    </table>
                `;
            }};

            return `
                                <section style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:16px 0;box-shadow:0 1px 2px rgba(16,24,40,.04);">
                                        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
                                            <h3 style="margin:0;">Turn ${{idx}}</h3>
                                            <span style="padding:4px 8px;border-radius:999px;font-size:12px;background:${{turn.status === 'success' ? '#dcfce7' : '#fee2e2'}};color:${{turn.status === 'success' ? '#166534' : '#991b1b'}};">${{esc(turn.status || '')}}</span>
                                        </div>
                    <p><b>turn_id:</b> ${{esc(turn.turn_id)}} | <b>status:</b> ${{esc(turn.status)}} | <b>duration_ms:</b> ${{esc(metrics.duration_ms)}}</p>
                    <p><b>tokens:</b> in=${{esc(token.input_tokens)}}, out=${{esc(token.output_tokens)}}, total=${{esc(token.total_tokens)}}</p>
                                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                                            <div>
                                                <h4 style="margin:8px 0;">User Input</h4>
                                                <pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:10px;border-radius:8px">${{esc(userMsg)}}</pre>
                                            </div>
                                            <div>
                                                <h4 style="margin:8px 0;">Assistant Output</h4>
                                                <pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:10px;border-radius:8px">${{esc(generation)}}</pre>
                                            </div>
                                        </div>
                                        <details style="margin-top:8px;"><summary>State snapshots</summary>
                                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px;">
                                                <div><b>input state summary</b><pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:8px;border-radius:8px;max-height:260px;overflow:auto;">${{esc(pretty(turn.input?.state_summary || null))}}</pre></div>
                                                <div><b>output state summary</b><pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:8px;border-radius:8px;max-height:260px;overflow:auto;">${{esc(pretty(turn.output?.state_summary || null))}}</pre></div>
                                            </div>
                                        </details>
                    ${{renderTable('Nodes', timeline.nodes || [], 'node')}}
                    ${{renderTable('Tools', timeline.tools || [], 'tool')}}
                    ${{renderTable('Models', timeline.models || [], 'model')}}
                </section>
            `;
        }}

        function buildReportHtml(jsonlPath, turns) {{
            const convId = turns[0]?.conversation_id || jsonlPath;
            const cards = turns.map((t, i) => buildTurnCard(t, i + 1)).join('');
            return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Browser Generated Report</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:24px;background:#f7f8fa;color:#1f2937}}.container{{max-width:1200px;margin:0 auto}}</style>
</head><body><div class="container"><h1>Browser Generated Report</h1><p><b>source:</b> ${{esc(jsonlPath)}}</p><p><b>conversation_id:</b> ${{esc(convId)}} | <b>turns:</b> ${{turns.length}}</p>${{cards || '<p>No valid rows found.</p>'}}</div></body></html>`;
        }}

        async function generateReportFromJsonl(jsonlPath) {{
            try {{
                const resp = await fetch(jsonlPath);
                if (!resp.ok) throw new Error(`HTTP ${{resp.status}}`);
                const text = await resp.text();
                const turns = parseJsonl(text);
                const html = buildReportHtml(jsonlPath, turns);
                const blob = new Blob([html], {{ type: 'text/html;charset=utf-8' }});
                const url = URL.createObjectURL(blob);
                window.open(url, '_blank');
            }} catch (e) {{
                alert('리포트 생성 실패: ' + e.message + '\\n(파일을 로컬 file://로 열었으면 fetch 제약이 있을 수 있습니다)');
            }}
        }}

        function _setFolderStatus(text) {{
            const el = document.getElementById('folderStatus');
            if (el) el.textContent = text;
        }}

        function _formatDate(ts) {{
            const d = new Date(ts);
            const pad = (n) => String(n).padStart(2, '0');
            return `${{d.getFullYear()}}-${{pad(d.getMonth()+1)}}-${{pad(d.getDate())}} ${{pad(d.getHours())}}:${{pad(d.getMinutes())}}:${{pad(d.getSeconds())}}`;
        }}

        async function connectLogsFolder() {{
            if (!window.showDirectoryPicker) {{
                alert('이 브라우저는 폴더 직접 연결(File System Access API)을 지원하지 않습니다.');
                return;
            }}

            try {{
                connectedDirHandle = await window.showDirectoryPicker();
                await syncConnectedFolder(true);
            }} catch (e) {{
                if (e && e.name !== 'AbortError') alert('폴더 연결 실패: ' + e.message);
            }}
        }}

        async function _readTextFromHandle(fileHandle) {{
            const file = await fileHandle.getFile();
            return await file.text();
        }}

        async function _openJsonlFromHandle(fileName) {{
            const handle = jsonlHandleMap.get(fileName);
            if (!handle) return;
            const file = await handle.getFile();
            const url = URL.createObjectURL(file);
            window.open(url, '_blank');
        }}

        async function _openHtmlFromHandle(fileName) {{
            const handle = htmlHandleMap.get(fileName);
            if (!handle) return;
            const file = await handle.getFile();
            const url = URL.createObjectURL(file);
            window.open(url, '_blank');
        }}

        async function _generateReportFromHandle(fileName) {{
            const handle = jsonlHandleMap.get(fileName);
            if (!handle) return;

            const text = await _readTextFromHandle(handle);
            const turns = parseJsonl(text);
            const htmlText = buildReportHtml(fileName, turns);
            const blob = new Blob([htmlText], {{ type: 'text/html;charset=utf-8' }});
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank');
        }}

        async function _generateAndSaveHtml(fileName) {{
            if (!connectedDirHandle) return;
            const jsonlHandle = jsonlHandleMap.get(fileName);
            if (!jsonlHandle) return;

            const text = await _readTextFromHandle(jsonlHandle);
            const turns = parseJsonl(text);
            const htmlText = buildReportHtml(fileName, turns);

            const htmlName = fileName.replace(/\\.jsonl$/i, '.html');
            const htmlHandle = await connectedDirHandle.getFileHandle(htmlName, {{ create: true }});
            const writable = await htmlHandle.createWritable();
            await writable.write(htmlText);
            await writable.close();

            htmlHandleMap.set(htmlName, htmlHandle);
        }}

        function _buildRowFromParsed(item) {{
            const htmlCell = item.htmlExists
                ? `<button onclick="_openHtmlFromHandle('${{esc(item.htmlName)}}')">open report</button>`
                : `<span class="muted">not generated</span>`;

            const syncBadge = item.htmlExists
                ? (item.html_state === 'stale'
                    ? `<span style="padding:2px 8px;border-radius:999px;background:#fff7ed;color:#9a3412;font-size:12px;">stale</span>`
                    : `<span style="padding:2px 8px;border-radius:999px;background:#dcfce7;color:#166534;font-size:12px;">fresh</span>`)
                : `<span style="padding:2px 8px;border-radius:999px;background:#fee2e2;color:#991b1b;font-size:12px;">missing</span>`;

            return `
                <tr>
                    <td>${{esc(item.conversation_id)}}</td>
                    <td><button onclick="_openJsonlFromHandle('${{esc(item.jsonlName)}}')">open jsonl</button></td>
                    <td>${{htmlCell}}<div style="margin-top:6px;">${{syncBadge}}</div></td>
                    <td style="display:flex;gap:6px;flex-wrap:wrap;">
                      <button onclick="_generateReportFromHandle('${{esc(item.jsonlName)}}')">generate in page</button>
                      <button onclick="_generateAndSaveHtml('${{esc(item.jsonlName)}}')">generate & save</button>
                    </td>
                    <td>${{esc(item.turns)}}</td>
                    <td>${{esc(item.provider)}}</td>
                    <td>${{esc(item.model)}}</td>
                    <td>${{esc(item.status)}}</td>
                    <td>${{esc(item.duration_ms)}}</td>
                    <td>${{esc(item.tokens)}}</td>
                    <td>${{esc(item.updated_at)}}</td>
                </tr>
            `;
        }}

        function _buildRowFromParsed(item) {{
            const htmlCell = item.htmlExists
                ? `<a href="${{esc(item.htmlLink)}}" target="_blank">open report</a>`
                : `<span class="muted">not generated</span>`;

            return `
                <tr>
                    <td>${{esc(item.conversation_id)}}</td>
                    <td><a href="${{esc(item.jsonlLink)}}" target="_blank">jsonl</a></td>
                    <td>${{htmlCell}}</td>
                    <td><button onclick="generateReportFromJsonl('${{esc(item.jsonlLink)}}')">generate in page</button></td>
                    <td>${{esc(item.turns)}}</td>
                    <td>${{esc(item.provider)}}</td>
                    <td>${{esc(item.model)}}</td>
                    <td>${{esc(item.status)}}</td>
                    <td>${{esc(item.duration_ms)}}</td>
                    <td>${{esc(item.tokens)}}</td>
                    <td>${{esc(item.updated_at)}}</td>
                </tr>
            `;
        }}

        function _summarizeFromTurns(conversationId, turns, updatedAt, jsonlLink, htmlLink, htmlExists, htmlState = 'missing') {{
            const first = turns[0] || {{}};
            const last = turns[turns.length - 1] || first;
            let duration = 0;
            let tokens = 0;

            turns.forEach(t => {{
                const m = t.metrics || {{}};
                const tu = m.token_usage || {{}};
                duration += Number(m.duration_ms || 0);
                tokens += Number(tu.total_tokens || 0);
            }});

            return {{
                conversation_id: conversationId,
                jsonlLink,
                htmlLink,
                htmlExists,
                html_state: htmlState,
                turns: turns.length,
                provider: last.provider || first.provider || '',
                model: last.model || first.model || '',
                status: last.status || first.status || '',
                duration_ms: duration,
                tokens,
                updated_at: updatedAt,
            }};
        }}

        async function syncConnectedFolder(generateMissing) {{
            if (!connectedDirHandle) {{
                _setFolderStatus('폴더가 연결되지 않았습니다. connect logs folder를 눌러주세요.');
                return;
            }}

            jsonlHandleMap.clear();
            htmlHandleMap.clear();
            const items = [];

            for await (const [name, handle] of connectedDirHandle.entries()) {{
                if (handle.kind !== 'file') continue;
                if (/^conv_.*\\.jsonl$/i.test(name)) jsonlHandleMap.set(name, handle);
                if (/^conv_.*\\.html$/i.test(name)) htmlHandleMap.set(name, handle);
            }}

            const jsonlNames = Array.from(jsonlHandleMap.keys()).sort();
            if (!jsonlNames.length) {{
                const tbody = document.getElementById('logsTbody');
                if (tbody) tbody.innerHTML = '<tr><td colspan="11">No log files found.</td></tr>';
                _setFolderStatus('연결된 폴더에 conv_*.jsonl 파일이 없습니다.');
                return;
            }}

            let generatedCount = 0;
            let updatedCount = 0;

            for (const jsonlName of jsonlNames) {{
                const jsonlHandle = jsonlHandleMap.get(jsonlName);
                const file = await jsonlHandle.getFile();
                const text = await file.text();
                const turns = parseJsonl(text);
                if (!turns.length) continue;

                const convId = (turns[0] && turns[0].conversation_id) || jsonlName.replace(/\\.jsonl$/i, '');
                const updatedAt = _formatDate(file.lastModified);
                const htmlName = jsonlName.replace(/\\.jsonl$/i, '.html');
                let htmlExists = htmlHandleMap.has(htmlName);
                let htmlState = htmlExists ? 'fresh' : 'missing';

                if (htmlExists) {{
                    try {{
                        const htmlFile = await htmlHandleMap.get(htmlName).getFile();
                        if ((htmlFile.lastModified || 0) < (file.lastModified || 0)) {{
                            htmlState = 'stale';
                        }}
                    }} catch (_) {{
                        htmlState = 'stale';
                    }}
                }}

                if (generateMissing && (!htmlExists || htmlState === 'stale')) {{
                    await _generateAndSaveHtml(jsonlName);
                    const regeneratedExists = htmlHandleMap.has(htmlName);
                    if (regeneratedExists) {{
                        if (!htmlExists) generatedCount += 1;
                        else updatedCount += 1;
                        htmlExists = true;
                        htmlState = 'fresh';
                    }}
                }}

                items.push(
                    _summarizeFromTurns(
                        convId,
                        turns,
                        updatedAt,
                        jsonlName,
                        htmlName,
                        htmlExists,
                        htmlState,
                    )
                );
            }}

            items.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
            const tbody = document.getElementById('logsTbody');
            if (!tbody) return;

            tbody.innerHTML = items.length
                ? items.map(_buildRowFromParsed).join('')
                : '<tr><td colspan="11">No log files found.</td></tr>';

            const total = document.getElementById('totalConversations');
            if (total) total.textContent = `total conversations: ${{items.length}} (connected folder)`;

            _setFolderStatus(
                generateMissing
                    ? `동기화 완료: ${{items.length}}개 로그 확인, HTML 신규 ${{generatedCount}}개 생성 / 기존 ${{updatedCount}}개 업데이트.`
                    : `새로고침 완료: ${{items.length}}개 로그 확인.`
            );
        }}

        function toggleAutoSync() {{
            const btn = document.getElementById('autoSyncBtn');
            if (autoSyncTimer) {{
                clearInterval(autoSyncTimer);
                autoSyncTimer = null;
                if (btn) btn.textContent = 'auto-sync: off';
                _setFolderStatus('auto-sync 비활성화');
                return;
            }}

            autoSyncTimer = setInterval(() => {{
                syncConnectedFolder(true).catch(() => null);
            }}, 5000);
            if (btn) btn.textContent = 'auto-sync: on';
            _setFolderStatus('auto-sync 활성화 (5초 간격)');
        }}

        // 기존 fallback(파일 선택) 유지
        function pickLogsFolder() {{
            const picker = document.getElementById('folderPicker');
            if (!picker) return;
            picker.value = '';
            picker.click();
        }}

        async function refreshRowsFromFolderFiles(files) {{
            const jsonlFiles = Array.from(files || []).filter(f => /(^|\\/)conv_.*\\.jsonl$/i.test(f.webkitRelativePath || f.name));
            if (!jsonlFiles.length) {{
                alert('conv_*.jsonl 파일을 찾지 못했습니다. logs/chatbot 폴더를 선택해 주세요.');
                return;
            }}

            const items = [];
            for (const file of jsonlFiles) {{
                const text = await file.text();
                const turns = parseJsonl(text);
                if (!turns.length) continue;

                const convId = (turns[0] && turns[0].conversation_id) || file.name.replace(/\\.jsonl$/i, '');
                const updatedAt = new Date(file.lastModified).toISOString().replace('T', ' ').slice(0, 19);
                const jsonlLink = URL.createObjectURL(file);
                const htmlLink = '';

                items.push(_summarizeFromTurns(convId, turns, updatedAt, jsonlLink, htmlLink, false));
            }}

            items.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
            const tbody = document.getElementById('logsTbody');
            if (!tbody) return;

            tbody.innerHTML = items.length
                ? items.map(_buildRowFromParsed).join('')
                : '<tr><td colspan="11">No log files found.</td></tr>';

            const total = document.getElementById('totalConversations');
            if (total) total.textContent = `total conversations: ${{items.length}} (folder refresh)`;
        }}

        document.getElementById('folderPicker')?.addEventListener('change', async (e) => {{
            const files = e.target && e.target.files ? e.target.files : [];
            await refreshRowsFromFolderFiles(files);
        }});
    </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate index HTML for chatbot JSONL logs")
    parser.add_argument("--logs-dir", default="logs/chatbot", help="Directory containing conv_*.jsonl")
    parser.add_argument("--output", default=None, help="Output HTML path (default: <logs-dir>/index.html)")
    args = parser.parse_args()

    logs_dir = Path(args.logs_dir).expanduser().resolve()
    if not logs_dir.exists() or not logs_dir.is_dir():
        raise NotADirectoryError(f"Invalid logs directory: {logs_dir}")

    output_path = Path(args.output).expanduser().resolve() if args.output else (logs_dir / "index.html")
    rows = _collect_rows(logs_dir)
    html_text = _build_html(rows, output_path, logs_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")

    print(f"[OK] Log index generated: {output_path}")


if __name__ == "__main__":
    main()
