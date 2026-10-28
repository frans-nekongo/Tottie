"""Tottie eval harness: every scenario in scenarios.jsonl runs twice (memory
ON and OFF) against a RUNNING core server, graded by substring rules.

Usage:
  TOTTIE_INLINE_WRITE=1 uvicorn app.main:app &   # server MUST inline writes
  PYTHONPATH=.. ./venv/bin/python eval/harness.py [--limit N] [--types fact]
      [--out report.json]

Metrics: ON accuracy, contradiction-correctness (contradiction subset),
OFF leak rate (OFF arm must NOT know), memory-hit rate (expected text in
the card), tokens/query ON vs OFF, p50/p95 ON latency. Exit 0 = ran clean
(infra green); accuracy numbers are reported, never thresholded here — R3
reads them as a judge. Any 5xx/connection error fails loud (exit 1).
"""
import argparse
import json
import os
import sys
import time
import urllib.request

CORE = os.environ.get("TOTTIE_CORE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("TOTTIE_API_TOKEN", "")
HERE = os.path.dirname(os.path.abspath(__file__))


def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        CORE + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except ValueError:
            detail = {}
        return e.code, detail


def _fail(msg):
    print(f"HARNESS FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _has(text, needles):
    low = (text or "").lower()
    return all(n.lower() in low for n in needles)


def _lacks(text, needles):
    low = (text or "").lower()
    return all(n.lower() not in low for n in needles)


def run_scenario(sc):
    owner = f"eval_{sc['id']}"
    session = f"eval_{sc['id']}"
    for i, turn in enumerate(sc["setup"]):
        code, out = _req("POST", "/write", {
            "text": turn, "session_id": session, "turn": i,
            "owner": owner, "source": {"trust": "user_direct"},
        })
        if code != 202:
            _fail(f"{sc['id']}: setup write {i} -> {code} {out}")
        if out.get("mode") != "inline":
            _fail(f"{sc['id']}: server is queued; "
                  "run core with TOTTIE_INLINE_WRITE=1 for eval")
    t0 = time.monotonic()
    code, on = _req("POST", "/chat", {
        "text": sc["ask"], "session_id": session, "owner": owner,
        "memory": True,
    })
    on_ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        _fail(f"{sc['id']}: ON chat -> {code} {on}")
    code, off = _req("POST", "/chat", {
        "text": sc["ask"], "session_id": session, "owner": owner,
        "memory": False,
    })
    if code != 200:
        _fail(f"{sc['id']}: OFF chat -> {code} {off}")
    on_ok = _has(on["reply"], sc["on_contains"]) and _lacks(
        on["reply"], sc.get("on_missing", []))
    hit = _has(on.get("card") or "", sc.get("card_contains", []))
    leak = not _lacks(off["reply"], sc["off_missing"])
    on_tok = on.get("tokens") or {}
    off_tok = off.get("tokens") or {}
    return {
        "id": sc["id"], "type": sc["type"], "on_ok": on_ok, "hit": hit,
        "off_leak": leak, "on_ms": on_ms,
        "on_tokens": on_tok.get("prompt", 0) + on_tok.get("completion", 0),
        "off_tokens": off_tok.get("prompt", 0) + off_tok.get("completion", 0),
        "model": on.get("model"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--types", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if not TOKEN:
        _fail("TOTTIE_API_TOKEN is empty (never print it; just set it)")
    code, out = _req("GET", "/health")
    if code != 200:
        _fail(f"core at {CORE} unhealthy ({code}); start it first")
    scenarios = [
        json.loads(line) for line in
        open(os.path.join(HERE, "scenarios.jsonl")) if line.strip()
    ]
    want = {t.strip() for t in args.types.split(",") if t.strip()}
    if want:
        scenarios = [s for s in scenarios if s["type"] in want]
    if args.limit:
        scenarios = scenarios[: args.limit]
    print(f"{len(scenarios)} scenarios vs {CORE} "
          f"(model pins recorded per reply)")
    results = []
    for sc in scenarios:
        r = run_scenario(sc)
        results.append(r)
        flag = "OK " if r["on_ok"] else "MISS"
        leak = " LEAK!" if r["off_leak"] else ""
        print(f"  [{flag}] {r['id']} ({r['type']}) hit={r['hit']}{leak} "
              f"{r['on_ms']}ms tok={r['on_tokens']}/{r['off_tokens']}")
    n = len(results)
    on_acc = sum(r["on_ok"] for r in results) / n
    contra = [r for r in results if r["type"] == "contradiction"]
    contra_acc = (sum(r["on_ok"] for r in contra) / len(contra)) if contra else None
    leak_rate = sum(r["off_leak"] for r in results) / n
    hit_rate = sum(r["hit"] for r in results) / n
    lat = sorted(r["on_ms"] for r in results)
    p50 = lat[len(lat) // 2]
    p95 = lat[max(0, int(len(lat) * 0.95) - 1)]
    report = {
        "n": n, "on_accuracy": round(on_acc, 3),
        "contradiction_correctness": (
            round(contra_acc, 3) if contra_acc is not None else None),
        "off_leak_rate": round(leak_rate, 3),
        "hit_rate": round(hit_rate, 3),
        "tokens_per_query_on": round(
            sum(r["on_tokens"] for r in results) / n, 1),
        "tokens_per_query_off": round(
            sum(r["off_tokens"] for r in results) / n, 1),
        "latency_on_p50_ms": p50, "latency_on_p95_ms": p95,
        "results": results,
    }
    print("---- report ----")
    for k, v in report.items():
        if k != "results":
            print(f"  {k}: {v}")
    print(f"  models: {sorted({r['model'] for r in results})}")
    if args.out:
        json.dump(report, open(args.out, "w"), indent=2)
        print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
