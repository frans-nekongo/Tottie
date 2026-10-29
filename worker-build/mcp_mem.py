#!/usr/bin/env python3
"""Atlas's tiny MCP stdio client (stdlib only).

Spawns tottie/core/server.py with the mandated env and speaks MCP
JSON-RPC over stdio. One tool call per process invocation:

  python3 mcp_mem.py memory.recall '{"query":"...","session_id":"atlas-day1"}'
  python3 mcp_mem.py memory.remember '{"text":"...","session_id":"atlas-day1"}'
  python3 mcp_mem.py --list-tools

Prints the tool's text payload (parsed JSON pretty-printed when possible).
Exit 0 on success, 1 on tool/error failure.
"""
import json
import os
import subprocess
import sys
import time

CORE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core"))
SERVER_PY = os.path.join(CORE_DIR, "server.py")
VENV_PY = os.path.join(CORE_DIR, "venv", "bin", "python")


def spawn():
    env = dict(os.environ)
    env["TOTTIE_API_TOKEN"] = "changeme-local-token"
    env["TOTTIE_OWNER"] = "owner_local"
    env["PYTHONPATH"] = CORE_DIR + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [VENV_PY, SERVER_PY],
        cwd=CORE_DIR,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    return proc


def send(proc, obj):
    line = json.dumps(obj)
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def recv(proc, timeout=180):
    # Blocking readline with a soft alarm via polling would need threads;
    # the server is local so a plain blocking read with overall patience is OK.
    # We implement a deadline by reading in a helper thread.
    import threading

    box = {}
    t = threading.Thread(
        target=lambda: box.setdefault("line", proc.stdout.readline()), daemon=True
    )
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None
    return box.get("line") or None


def handshake(proc):
    send(proc, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "atlas-mcp-mem", "version": "1.0"},
        },
    })
    resp = recv(proc)
    if not resp:
        err = read_stderr(proc)
        raise RuntimeError(f"no initialize response. stderr:\n{err}")
    data = json.loads(resp)
    if "error" in data:
        raise RuntimeError(f"initialize error: {data['error']}")
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return data.get("result", {})


def call_tool(proc, name, args, call_id=2):
    send(proc, {
        "jsonrpc": "2.0", "id": call_id, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    resp = recv(proc)
    if not resp:
        err = read_stderr(proc)
        raise RuntimeError(f"no tools/call response. stderr:\n{err}")
    return json.loads(resp)


def list_tools(proc):
    send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    resp = recv(proc)
    if not resp:
        raise RuntimeError("no tools/list response")
    return json.loads(resp)


def read_stderr(proc):
    try:
        import select

        out = []
        while select.select([proc.stderr], [], [], 0)[0]:
            chunk = proc.stderr.read(65536)
            if not chunk:
                break
            out.append(chunk)
        return "".join(out)[-4000:]
    except Exception:
        return "<stderr unreadable>"


def extract_text(result):
    """Unwrap MCP tools/call result -> text payload."""
    if "error" in result:
        return None, f"JSON-RPC error: {result['error']}"
    res = result.get("result", {})
    if res.get("isError"):
        parts = res.get("content", [])
        txt = " ".join(p.get("text", "") for p in parts)
        return None, f"tool error: {txt}"
    parts = res.get("content", [])
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "\n".join(texts), None


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    t0 = time.time()
    proc = spawn()
    try:
        handshake(proc)
        if argv[1] == "--list-tools":
            print(json.dumps(list_tools(proc), indent=2)[:6000])
            return 0
        name = argv[1]
        args = json.loads(argv[2]) if len(argv) > 2 else {}
        result = call_tool(proc, name, args)
        text, err = extract_text(result)
        if err:
            print(err, file=sys.stderr)
            print("stderr tail:\n" + read_stderr(proc), file=sys.stderr)
            return 1
        # Pretty-print if the payload is JSON.
        try:
            print(json.dumps(json.loads(text), indent=2))
        except (ValueError, TypeError):
            print(text)
        print(f"\n[mcp_mem: {name} ok in {time.time()-t0:.1f}s]",
              file=sys.stderr)
        return 0
    except Exception as e:
        print(f"mcp_mem failed: {e}", file=sys.stderr)
        print("stderr tail:\n" + read_stderr(proc), file=sys.stderr)
        return 1
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main(sys.argv))
