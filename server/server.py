"""
AWP RP Bridge Server — HTTP server + static frontend.

Provides an optional standalone web frontend for the AWP RP system,
alongside the ComfyUI node interface. Inspired by oh-story-claudecode's
server.py architecture.

Usage:
    python server.py [--port=8765] [--project-root=<path>]

Endpoints:
    GET  /                    — Static frontend (index.html)
    POST /api/generate        — Submit user input, trigger generation
    GET  /api/status          — System status
    POST /api/settings        — Update settings
    GET  /api/session/{id}    — Get session history
    POST /api/reroll          — Reroll last turn
    POST /api/delete_turns    — Delete turns from index
"""

import http.server
import json
import os
import sys
import urllib.parse
from pathlib import Path

PORT = 8765
ROOT = Path(__file__).parent
SERVER_DIR = ROOT

# HTML frontend — self-contained single page
FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AWP RP Console</title>
<style>
:root { --bg:#0f0f1a; --card:#1a1a2e; --accent:#6c63ff; --text:#e0e0e0; --input-bg:#12122a; --border:#2a2a4a; }
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; display:flex; height:100vh; overflow:hidden; }
.sidebar { width:280px; background:var(--card); padding:16px; border-right:1px solid var(--border); display:flex; flex-direction:column; gap:12px; }
.main { flex:1; display:flex; flex-direction:column; }
.header { padding:16px; border-bottom:1px solid var(--border); font-size:18px; font-weight:600; }
.turns { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:16px; }
.turn { padding:12px; border-radius:8px; max-width:85%; }
.turn-user { background:var(--input-bg); align-self:flex-end; }
.turn-ai { background:var(--card); align-self:flex-start; border:1px solid var(--border); }
.turn-role { font-size:11px; color:var(--accent); margin-bottom:4px; }
.turn-text { font-size:14px; line-height:1.6; white-space:pre-wrap; }
.input-area { padding:16px; border-top:1px solid var(--border); display:flex; gap:8px; }
.input-area textarea { flex:1; background:var(--input-bg); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:12px; font-size:14px; resize:none; height:60px; font-family:inherit; }
.input-area button { background:var(--accent); color:#fff; border:none; border-radius:8px; padding:12px 24px; cursor:pointer; font-size:14px; font-weight:600; }
.input-area button:hover { opacity:0.9; }
.status { padding:12px 16px; font-size:12px; color:#888; border-top:1px solid var(--border); }
.options { display:flex; gap:6px; flex-wrap:wrap; padding:4px 0; }
.opt-btn { background:var(--input-bg); border:1px solid var(--border); border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer; color:var(--text); }
.opt-btn:hover { border-color:var(--accent); }
.settings label { display:block; font-size:12px; margin:8px 0 4px; color:#aaa; }
.settings input,.settings select { width:100%; background:var(--input-bg); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px 10px; font-size:13px; }
.sidebar h3 { font-size:13px; color:#aaa; text-transform:uppercase; letter-spacing:1px; }
.tokens { font-size:11px; color:#666; margin-top:4px; }
.loading { text-align:center; padding:40px; color:#888; }
</style>
</head>
<body>
<div class="sidebar">
    <h3>AWP RP Console</h3>
    <div class="settings">
        <label>Session ID</label>
        <input id="sessionId" value="default">
        <label>Provider</label>
        <select id="provider"><option>deepseek</option></select>
        <label>Profile</label>
        <select id="profile"><option>rp-writer</option><option>rp-critic</option><option>novel-long-writer</option></select>
    </div>
    <div style="display:flex;gap:8px;">
        <button onclick="reroll()" style="flex:1;background:#b0624a;color:#fff;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:13px;">Reroll</button>
        <button onclick="clearSession()" style="flex:1;background:#333;color:#fff;border:none;border-radius:6px;padding:8px;cursor:pointer;font-size:13px;">Clear</button>
    </div>
    <div class="status" id="status">Ready</div>
</div>
<div class="main">
    <div class="header">Turn History</div>
    <div class="turns" id="turns"><div class="loading">Enter your action below to begin...</div></div>
    <div class="input-area">
        <textarea id="userInput" placeholder="Type your action, dialogue, or command..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();submit();}"></textarea>
        <button onclick="submit()">Send</button>
    </div>
</div>
<script>
let state = { session:'default', turns:[], generating:false };
document.getElementById('sessionId').onchange = e => state.session = e.target.value;

async function submit() {
    const input = document.getElementById('userInput').value.trim();
    if (!input || state.generating) return;
    state.generating = true;
    document.getElementById('userInput').value = '';
    document.getElementById('status').textContent = 'Generating...';
    
    addTurn('user', input);
    
    try {
        const res = await fetch('/api/generate', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
                text:input,
                session_id:state.session,
                provider:document.getElementById('provider').value,
                profile:document.getElementById('profile').value,
            })
        });
        const data = await res.json();
        if (data.ok) {
            addTurn('ai', data.reply);
            if (data.options && data.options.length) renderOptions(data.options);
            document.getElementById('status').textContent = `Turn ${data.metadata?.turn_index||'?'} | Tokens: in=${data.metadata?.token_usage?.input||0} out=${data.metadata?.token_usage?.output||0}`;
        } else {
            document.getElementById('status').textContent = 'Error: ' + (data.error||'unknown');
        }
    } catch(e) {
        document.getElementById('status').textContent = 'Error: ' + e.message;
    }
    state.generating = false;
}

function addTurn(role, text) {
    state.turns.push({role, text});
    const div = document.createElement('div');
    div.className = 'turn ' + (role==='user'?'turn-user':'turn-ai');
    div.innerHTML = `<div class="turn-role">${role==='user'?'You':'Narrative'}</div><div class="turn-text">${text}</div>`;
    document.getElementById('turns').appendChild(div);
    div.scrollIntoView({behavior:'smooth'});
    if (state.turns.length===1 && role==='user') document.getElementById('turns').innerHTML='';
}

function renderOptions(opts) {
    const container = document.createElement('div');
    container.className = 'options';
    opts.forEach(o => {
        const btn = document.createElement('button');
        btn.className = 'opt-btn';
        btn.innerHTML = o;
        btn.onclick = () => { document.getElementById('userInput').value = o.replace(/<[^>]+>/g,''); submit(); };
        container.appendChild(btn);
    });
    document.getElementById('turns').lastElementChild.appendChild(container);
}

async function reroll() {
    try {
        await fetch('/api/reroll', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:state.session})});
        location.reload();
    } catch(e) { document.getElementById('status').textContent = 'Reroll failed'; }
}

async function clearSession() {
    if (!confirm('Clear all turns?')) return;
    try {
        await fetch('/api/delete_turns', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:state.session,from_index:0})});
        location.reload();
    } catch(e) { document.getElementById('status').textContent = 'Clear failed'; }
}
</script>
</body>
</html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with API endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVER_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self._serve_html(FRONTEND_HTML)
            return

        if parsed.path == "/api/status":
            self._json({"status": "running", "port": PORT})
            return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {"text": body}

        if parsed.path == "/api/generate":
            self._handle_generate(data)
        elif parsed.path == "/api/reroll":
            self._handle_reroll(data)
        elif parsed.path == "/api/delete_turns":
            self._handle_delete_turns(data)
        elif parsed.path == "/api/settings":
            self._json({"ok": True, "settings": data})
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def _handle_generate(self, data: dict):
        """Handle generation request — delegates to MainAgent."""
        text = data.get("text", "").strip()
        if not text:
            self._json({"ok": False, "error": "empty input"})
            return

        # Delegate to the AWP RP system
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from comfyui_awp_rp.nodes.main_agent import AWPMainAgent

            agent = AWPMainAgent()
            reply, ctx, meta_str, vars_str, changes = agent.execute(
                user_input=text,
                session_id=data.get("session_id", "default"),
                provider=data.get("provider", "deepseek"),
                profile=data.get("profile", "rp-writer"),
                enable_agent_loop=data.get("enable_agent_loop", True),
            )

            # Extract options from reply
            options = _extract_action_options(reply)
            metadata = json.loads(meta_str) if meta_str else {}

            self._json({
                "ok": True,
                "reply": reply,
                "options": options,
                "metadata": metadata,
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"ok": False, "error": str(e)})

    def _handle_reroll(self, data: dict):
        try:
            from comfyui_awp_rp.memory.short_term import AgentSessionManager
            mgr = AgentSessionManager()
            key = mgr.create_key("default", "web-rp", data.get("session_id", "default"), "main-agent")
            user_input = mgr.reroll_last(key)
            self._json({"ok": True, "user_input": user_input or ""})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _handle_delete_turns(self, data: dict):
        try:
            from comfyui_awp_rp.memory.short_term import AgentSessionManager
            mgr = AgentSessionManager()
            key = mgr.create_key("default", "web-rp", data.get("session_id", "default"), "main-agent")
            deleted = mgr.delete_turns_from(key, data.get("from_index", 0))
            self._json({"ok": True, "deleted": deleted})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        if "POST" in fmt or "/api/" in fmt:
            print(f"[server] {fmt % args}")


def _extract_action_options(text: str) -> list[str]:
    """Extract <options> block from text."""
    import re
    match = re.search(r"<options>(.*?)</options>", text, re.DOTALL)
    if not match:
        return []
    return [line.strip() for line in match.group(1).strip().split("\n") if line.strip()]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AWP RP Bridge Server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--project-root", type=str, default=".")
    args = parser.parse_args()

    PORT = args.port
    print(f"\n  AWP RP Bridge Server")
    print(f"  Frontend: http://localhost:{PORT}")
    print(f"  Ctrl+C to stop\n")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] Shutting down...")
        server.shutdown()
