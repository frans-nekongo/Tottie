#!/usr/bin/env python3
"""Tottie memory battery v1: cognitive paradigms + agent-memory abilities,
no LLM judge anywhere. Every drill encodes via POST /write (raw turns,
never instructed remembering) and scores judge-free: recall@k by row id,
abstain booleans, link existence, liveness flags, intention firing.

Paradigm map (see docs/drill-battery.md):
  D1  paired associates / cued recall ............ recall@3 hit rate
  D2  A-B/A-D updates (retroactive interference) . newest top-1 + old dead
  D3  multi-hop chain (REACH, expected fail) ..... evidence in top-5
  D4  temporal order ............................. edge exists + direction
  D5  DRM lure (false memory) .................... abstain-or-clean + brief
  D6  misinformation (newest-wins contract) ...... served + linked + kept
  D7  prospective memory (intentions) ............ fires exactly once
  D8  interleaved counters (updating) ............ latest per entity top-1
  D9  NoLiMa paraphrase (zero overlap) ........... recall@5
  D10 plausible abstention ....................... abstain x3
  D11 cross-session reasoning .................... both sessions in top-5
  D12 linked story (cheese/vegetarian) ........... both surface + link
  D13 interference (D1 re-run) ................... delta vs D1

Usage (from core/):
  PGHOST=/tmp PGUSER=fransnekongo TOTTIE_API_TOKEN=... \
    ./venv/bin/python scripts/drill_battery.py [--drill D1] [--owner battery]
Exit code = number of failed drills (reach fails excluded).
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CORE = os.environ.get("TOTTIE_CORE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("TOTTIE_API_TOKEN", "changeme-local-token")
OWNER = "battery"
RESULTS: list[tuple[str, bool, str]] = []


def api(path, payload, timeout=180):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        CORE + path, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def sql(query, params=()):
    import psycopg
    conn = psycopg.connect(host=os.environ.get("PGHOST", "localhost"),
                           user=os.environ.get("PGUSER"),
                           dbname=os.environ.get("PGDATABASE", "tottie"))
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, row)) for row in (cur.fetchall() or [])]
    finally:
        conn.close()


def report(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name
          + (f" — {detail}" if detail else ""), flush=True)


def encode(session, turn, text, owner=None):
    r = api("/write", {"text": text, "session_id": session, "turn": turn,
                       "owner": owner or OWNER})
    assert "event_id" in r, r
    return r["event_id"]


def wait_for(token, owner=None, timeout=240):
    """Poll until a live row contains the key token. Returns row id."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = sql("SELECT id FROM memories WHERE owner = %s "
                   "AND valid_to IS NULL AND content ILIKE %s "
                   "ORDER BY created_at DESC LIMIT 1",
                   (owner or OWNER, f"%{token}%"))
        if rows:
            return str(rows[0]["id"])
        time.sleep(5)
    return ""


def recall(query, k=8, session="battery-probe", owner=None):
    return api("/recall", {"query": query, "session_id": session, "k": k,
                           "owner": owner or OWNER})


def brief(text, session="battery-brief", owner=None):
    d = api("/briefing", {"text": text, "session_id": session,
                          "owner": owner or OWNER})
    return d.get("briefing", "")


def hit_ids(out, k):
    return [h["id"] for h in out.get("hits", [])[:k]]


def summaries(out, k=8):
    return " ".join(h.get("summary", "") for h in out.get("hits", [])[:k])


def sweep(owner=None):
    api("/sweep", {"owner": owner or OWNER})


def wait_dead(row_id, timeout=300):
    """Poll until the row is superseded. Returns seconds or -1."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        rows = sql("SELECT valid_to FROM memories WHERE id = %s::uuid",
                   (row_id,))
        if rows and rows[0]["valid_to"] is not None:
            return round(time.monotonic() - t0, 1)
        time.sleep(5)
    return -1


PAIRS_D1 = [
    ("The garden shed code is 6110.", "garden shed code?", "6110"),
    ("Marta's locker number is 7245.", "Marta locker number?", "7245"),
    ("The bike lock combo is 8390.", "bike lock combo?", "8390"),
    ("The cabin door code is 9024.", "cabin door code?", "9024"),
    ("The storage unit pin is 1557.", "storage unit pin?", "1557"),
    ("The gate remote code is 3388.", "gate remote code?", "3388"),
    ("The safe combination is 4761.", "safe combination?", "4761"),
    ("The mailbox code is 5602.", "mailbox code?", "5602"),
]


def d1_paired_associates(sess="batt-d1"):
    """Cued recall: 8 pairs, cue each, target row id in top-3."""
    ids = {}
    for turn, (text, _cue, token) in enumerate(PAIRS_D1):
        encode(sess, turn, text)
        rid = wait_for(token)
        if not rid:
            report("D1", False, f"encode miss: {token} never stored")
            return
        ids[token] = rid
    hits = 0
    for _text, cue, token in PAIRS_D1:
        out = recall(cue, k=3, session=sess)
        if ids[token] in hit_ids(out, 3):
            hits += 1
    report("D1", hits == len(PAIRS_D1), f"cued recall@3 {hits}/{len(PAIRS_D1)}")


CHANGES_D2 = [
    ("The pool gate code is 4100.", "The pool gate code changed to 4333.",
     "pool gate code?", "4100", "4333"),
    ("The office alarm code is 5200.", "The office alarm code changed to 5444.",
     "office alarm code?", "5200", "5444"),
    ("The trailer hitch lock is 6300.", "The trailer hitch lock changed to 6555.",
     "trailer hitch lock?", "6300", "6555"),
]


def d2_updates(sess="batt-d2"):
    """A-B/A-D: change 3 codes, newest must top-1, old must die."""
    old_ids, new_ids = {}, {}
    for turn, (orig, _chg, _cue, old_tok, _new_tok) in enumerate(CHANGES_D2):
        encode(sess, turn, orig)
        rid = wait_for(old_tok)
        if not rid:
            report("D2", False, f"encode miss: {old_tok}")
            return
        old_ids[old_tok] = rid
    for i, (_orig, chg, _cue, _old_tok, new_tok) in enumerate(CHANGES_D2):
        encode(sess, 10 + i, chg)
        rid = wait_for(new_tok)
        if not rid:
            report("D2", False, f"update never stored: {new_tok}")
            return
        new_ids[new_tok] = rid
    sweep()
    latencies = {}
    for old_tok, rid in old_ids.items():
        latencies[old_tok] = wait_dead(rid)
    top1 = 0
    for _o, _c, cue, _ot, new_tok in CHANGES_D2:
        out = recall(cue, k=3, session=sess)
        if hit_ids(out, 3)[:1] == [new_ids[new_tok]]:
            top1 += 1
    dead = sum(1 for v in latencies.values() if v >= 0)
    ok = top1 == len(CHANGES_D2) and dead == len(CHANGES_D2)
    report("D2", ok, f"newest top-1 {top1}/{len(CHANGES_D2)}, "
                     f"old dead {dead}/{len(CHANGES_D2)} lat={latencies}")


def d3_multihop(sess="batt-d3"):
    """Chain retrieval: both evidence rows in top-5. Composition (a
    single answering row) is beyond recall-by-design; reported, and
    the drill scores the retrieval half only."""
    encode(sess, 0, "Ann's doctor is Doctor Bex.")
    encode(sess, 1, "Doctor Bex's clinic closes at five.")
    r1 = wait_for("Doctor Bex")
    r2 = wait_for("closes at five")
    if not (r1 and r2):
        report("D3", False, "chain failed to encode")
        return
    out = recall("When does Ann's doctor's clinic close?", k=5, session=sess)
    ids = hit_ids(out, 5)
    both = r1 in ids and r2 in ids
    composed = "five" in summaries(out, 1).lower()
    report("D3", both, f"chain rows in top-5: {both}, "
                       f"single-answer top-1: {composed} (no reader)")


def d4_temporal(sess="batt-d4"):
    """Event order: two events, one turn. Edge must exist; narrated
    direction (against turn order) is reported as info."""
    encode(sess, 0, "Yesterday the power failed. Earlier that morning "
                    "the generator was serviced.")
    r_pow = wait_for("power failed")
    r_gen = wait_for("generator was serviced")
    if not (r_pow and r_gen):
        report("D4", False, "events failed to encode")
        return
    link = []
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and not link:
        link = sql("SELECT src, dst, relation, reason FROM memory_links "
                   "WHERE owner = %s AND ((src = %s::uuid AND dst = %s::uuid) "
                   "OR (src = %s::uuid AND dst = %s::uuid))",
                   (OWNER, r_pow, r_gen, r_gen, r_pow))
        if not link:
            time.sleep(5)
    if not link:
        report("D4", False, "no link between the two events after 300s")
        return
    l0 = link[0]
    narrated_first = str(l0["src"]) == r_gen  # generator serviced first
    report("D4", True, f"{l0['relation']} edge, narrated-order "
                       f"{'kept' if narrated_first else 'FLIPPED'}: "
                       f"{(l0['reason'] or '')[:80]}")


DRM_TURNS = [
    "I need a new bed and a softer pillow for my room.",
    "After lunch I feel tired and drowsy at my desk.",
    "The baby had a bad dream and woke up crying at night.",
    "I hit the alarm, pulled the blanket up, and went back to my nap.",
]


def d5_drm_lure(sess="batt-d5"):
    """False memory: 12 sleep-associates, never the lure. Fails if the
    scribe invents 'sleep', if recall asserts it, or if brief injects it."""
    for turn, text in enumerate(DRM_TURNS):
        encode(sess, turn, text)
    time.sleep(30)  # let all four turns scribe before judging
    fab = sql("SELECT content FROM memories WHERE owner = %s "
              "AND valid_to IS NULL AND content ILIKE %s", (OWNER, "%sleep%"))
    if fab:
        report("D5", False, f"scribe fabricated the lure: {fab[0]['content'][:70]}")
        return
    out = recall("sleep", k=8, session=sess)
    asserted = "sleep" in summaries(out, 8).lower()
    block = brief("I need to sleep well tonight", session=sess)
    injected = any("sleep" in ln.lower()
                   for ln in block.splitlines() if ln.startswith("- "))
    ok = not asserted and not injected
    report("D5", ok, f"recall-asserts-lure={asserted} brief-injects={injected} "
                     f"abstain={out.get('abstain')}")


def d6_misinformation(sess="batt-d6"):
    """Newest-wins contract: misleading update is served (by design),
    but the original must stay linked and recoverable with provenance."""
    encode(sess, 0, "The review meeting is on Friday in room 4B.")
    r_fri = wait_for("Friday")
    encode(sess, 1, "Correction: the review meeting moved to Wednesday.")
    r_wed = wait_for("Wednesday")
    if not (r_fri and r_wed):
        report("D6", False, "failed to encode")
        return
    sweep()
    lat = wait_dead(r_fri)
    out = recall("When is the review meeting?", k=3, session=sess)
    served_new = hit_ids(out, 3)[:1] == [r_wed]
    link = sql("SELECT relation FROM memory_links WHERE owner = %s "
               "AND src = %s::uuid AND dst = %s::uuid", (OWNER, r_wed, r_fri))
    orig = sql("SELECT source FROM memories WHERE id = %s::uuid", (r_fri,))
    kept = bool(orig) and (orig[0]["source"] or {}).get("turn") == 0
    ok = served_new and lat >= 0 and bool(link) and kept
    report("D6", ok, f"served-new={served_new} dead-in={lat}s "
                     f"link={bool(link)} original-kept={kept}")


def d7_prospective(sess="batt-d7"):
    """Intentions: register on write, fire once on a tagged trigger
    (event cues match #tag/@/quote entities only), never refire. The
    plain-query no-fire is reported as a boundary, not a fail."""
    encode(sess, 0, "Remind me to call Marta when I finish the report.")
    pend = []
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline and not pend:
        pend = sql("SELECT id FROM intentions WHERE owner = %s "
                   "AND status = 'pending' AND content ILIKE %s",
                   (OWNER, "%Marta%"))
        if not pend:
            time.sleep(5)
    if not pend:
        report("D7", False, "intention never registered")
        return
    plain = recall("I finished the report, what should I do now?",
                   k=5, session=sess)
    plain_fired = any("Marta" in f.get("content", "")
                      for f in plain.get("fired_intentions", []))
    out1 = recall("finished the #report, what should I do now?",
                  k=5, session=sess)
    fired1 = [f.get("content", "") for f in out1.get("fired_intentions", [])]
    out2 = recall("finished the #report, anything else?", k=5, session=sess)
    fired2 = [f.get("content", "") for f in out2.get("fired_intentions", [])]
    once = sum("Marta" in f for f in fired1) == 1
    no_refire = not any("Marta" in f for f in fired2)
    report("D7", once and no_refire,
           f"fired-once={once} no-refire={no_refire} "
           f"plain-query-fires={plain_fired} (needs #tag: boundary)")


def d8_counters(sess="batt-d8"):
    """Updating under interference: interleaved alpha/beta counters,
    latest value per entity must top-1 after a sweep."""
    turns = [("Counter alpha is 1.", "alpha is 1"),
             ("Counter beta is 1.", "beta is 1"),
             ("Counter alpha is 2.", "alpha is 2"),
             ("Counter beta is 2.", "beta is 2"),
             ("Counter alpha is 3.", "alpha is 3")]
    for turn, (text, _tok) in enumerate(turns):
        encode(sess, turn, text)
    r_a3 = wait_for("alpha is 3")
    r_b2 = wait_for("beta is 2")
    if not (r_a3 and r_b2):
        report("D8", False, "counters failed to encode")
        return
    sweep()
    wait_dead_rows = []
    for tok in ("alpha is 1", "alpha is 2", "beta is 1"):
        rows = sql("SELECT id FROM memories WHERE owner = %s "
                   "AND valid_to IS NULL AND content ILIKE %s", (OWNER, f"%{tok}%"))
        wait_dead_rows += [str(r["id"]) for r in rows]
    for rid in wait_dead_rows:
        wait_dead(rid)
    out_a = recall("counter alpha?", k=3, session=sess)
    out_b = recall("counter beta?", k=3, session=sess)
    ok_a = hit_ids(out_a, 3)[:1] == [r_a3]
    ok_b = hit_ids(out_b, 3)[:1] == [r_b2]
    report("D8", ok_a and ok_b, f"alpha-latest-top1={ok_a} beta-latest-top1={ok_b}")


PARAPHRASES_D9 = [
    ("The garden shed code is 6110.", "what number opens the shed out back?",
     "6110"),
    ("Marta's locker number is 7245.", "which digits did we assign Marta's box?",
     "7245"),
    ("The bike lock combo is 8390.", "how do I open the bicycle lock?",
     "8390"),
]


def d9_paraphrase(sess="batt-d9"):
    """NoLiMa-style: cue shares (near-)zero words with the stored row.
    Target row id in top-5. Known gap class: scored, partial expected."""
    for turn, (fact, _cue, _token) in enumerate(PARAPHRASES_D9):
        # Repeats SKIP as familiarity when D1 ran; encode standalone too.
        encode(sess, turn, fact)
    for _fact, _cue, token in PARAPHRASES_D9:
        if not wait_for(token):
            report("D9", False, f"encode miss: {token}")
            return
    hits = 0
    for _fact, cue, token in PARAPHRASES_D9:
        rows = sql("SELECT id FROM memories WHERE owner = %s "
                   "AND valid_to IS NULL AND content ILIKE %s",
                   (OWNER, f"%{token}%"))
        if not rows:
            continue
        out = recall(cue, k=5, session=sess)
        if str(rows[0]["id"]) in hit_ids(out, 5):
            hits += 1
    report("D9", hits == len(PARAPHRASES_D9),
           f"zero-overlap recall@5 {hits}/{len(PARAPHRASES_D9)}")


ABSENT_D10 = [
    "What is the vault code for the Mars office?",
    "When does the dentist appointment start?",
    "What is the name of the landlord's dog?",
]


def d10_abstention(sess="batt-d10"):
    """Plausible-but-absent: must abstain, never confabulate."""
    ok = 0
    for cue in ABSENT_D10:
        out = recall(cue, k=5, session=sess)
        if out.get("abstain") is True:
            ok += 1
    report("D10", ok == len(ABSENT_D10), f"abstained {ok}/{len(ABSENT_D10)}")


def d11_cross_session():
    """Multi-session: fact in s1, related fact in s2, both in top-5."""
    encode("batt-d11a", 0, "The warehouse alarm code is 9012.")
    encode("batt-d11b", 0, "The warehouse alarm was installed by Bex Security.")
    r1 = wait_for("9012")
    r2 = wait_for("Bex Security")
    if not (r1 and r2):
        report("D11", False, "failed to encode")
        return
    out = recall("warehouse alarm?", k=5, session="batt-d11a")
    ids = hit_ids(out, 5)
    report("D11", r1 in ids and r2 in ids,
           f"s1-row={r1 in ids} s2-row={r2 in ids}")


def d12_linked_story(sess="batt-d12"):
    """The owner's case: cheese + vegetarian must both surface on a
    diet cue AND share a link that tells the story. Scribe paraphrase
    tolerant: matches any row carrying the key nouns, not verbatim."""
    encode(sess, 0, "I hate cheese, it makes me feel sick.")
    encode(sess, 1, "I am a vegetarian for health reasons.")
    if not wait_for("cheese") or not wait_for("vegetarian"):
        report("D12", False, "failed to encode")
        return
    cheese = sql("SELECT id FROM memories WHERE owner = %s "
                 "AND valid_to IS NULL AND content ILIKE %s", (OWNER, "%cheese%"))
    veg = sql("SELECT id FROM memories WHERE owner = %s "
              "AND valid_to IS NULL AND content ILIKE %s", (OWNER, "%vegetarian%"))
    cheese_ids = {str(r["id"]) for r in cheese}
    veg_ids = {str(r["id"]) for r in veg}
    out = recall("what is my diet?", k=5, session=sess)
    ids = set(hit_ids(out, 5))
    both = bool(cheese_ids & ids) and bool(veg_ids & ids)
    link = []
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and not link:
        link = sql("SELECT relation, reason FROM memory_links WHERE owner = %s "
                   "AND ((src = ANY(%s::uuid[]) AND dst = ANY(%s::uuid[])) "
                   "OR (src = ANY(%s::uuid[]) AND dst = ANY(%s::uuid[])))",
                   (OWNER, list(cheese_ids), list(veg_ids),
                    list(veg_ids), list(cheese_ids)))
        if not link:
            time.sleep(5)
    ok = both and bool(link)
    detail = f"both-surface={both} link={bool(link)}"
    if link:
        detail += f" ({link[0]['relation']}: {(link[0]['reason'] or '')[:70]})"
    report("D12", ok, detail)


def d13_interference(sess="batt-d13"):
    """Proactive/retroactive interference: re-cue all D1 pairs after
    the full battery. Anything lost vs D1 is interference damage."""
    rows = sql("SELECT id, content FROM memories WHERE owner = %s "
               "AND valid_to IS NULL AND source->>'session' = 'batt-d1'",
               (OWNER,))
    by_token = {}
    for _text, _cue, token in PAIRS_D1:
        match = [str(r["id"]) for r in rows if token in (r["content"] or "")]
        by_token[token] = match[0] if match else ""
    hits = 0
    for _text, cue, token in PAIRS_D1:
        if not by_token[token]:
            continue
        out = recall(cue, k=3, session=sess)
        if by_token[token] in hit_ids(out, 3):
            hits += 1
    report("D13", hits == len(PAIRS_D1),
           f"post-battery cued recall@3 {hits}/{len(PAIRS_D1)}")


DRILLS = [
    ("D1", d1_paired_associates), ("D2", d2_updates), ("D3", d3_multihop),
    ("D4", d4_temporal), ("D5", d5_drm_lure), ("D6", d6_misinformation),
    ("D7", d7_prospective), ("D8", d8_counters), ("D9", d9_paraphrase),
    ("D10", d10_abstention), ("D11", d11_cross_session),
    ("D12", d12_linked_story), ("D13", d13_interference),
]


def main():
    global OWNER
    ap = argparse.ArgumentParser()
    ap.add_argument("--drill", default=None, help="run one drill e.g. D1")
    ap.add_argument("--owner", default="battery")
    args = ap.parse_args()
    OWNER = args.owner
    picked = [(n, f) for n, f in DRILLS
              if args.drill is None or n == args.drill.upper()]
    if not picked:
        print(f"unknown drill {args.drill}")
        return 2
    t0 = time.monotonic()
    for _n, fn in picked:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a crashed drill is data
            report(fn.__name__, False, f"CRASH: {type(e).__name__}: {e}"[:160])
    fails = [n for n, ok, _d in RESULTS if not ok]
    print(f"\n{battery_score()} ({time.monotonic() - t0:.0f}s)", flush=True)
    return len(fails)


def battery_score():
    n = len(RESULTS)
    p = sum(1 for _n, ok, _d in RESULTS if ok)
    return f"battery: {p}/{n} drills passed"


if __name__ == "__main__":
    raise SystemExit(main())
