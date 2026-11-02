"""Battery v2: the four hardest memory bottlenecks (LongMemEval/LoCoMo gold
standard + human literature via the META notebook). Temporal order,
prospective surfacing, source monitoring, fan interference, noisy
updates, flip-flop corrections. Judge-free: row ids, abstain flags,
brief lines only. No mocks — every row is a real /write, every probe a
real /recall or /briefing. Each drill takes its own owner.

Usage: PGHOST=/tmp PGUSER=fransnekongo ./venv/bin/python
       scripts/drill_battery2.py [--drill T1]
"""
import argparse
import sys
import time

sys.path.insert(0, "scripts")
from drill_battery import (RESULTS, api, battery_score, brief, encode,
                           hit_ids, recall, report, sql, sweep, summaries,
                           wait_dead, wait_for)


def t1_temporal_next(sess="hb-t1", owner="hardT1f"):
    """Temporal reasoning (LongMemEval's hardest category): 5-stop chain,
    probe the stop AFTER a named one. Similarity favors the named row;
    only sequence knowledge answers right."""
    stops = ["Windhoek", "Otjiwarongo", "Frankfurt", "Berlin", "Marta"]
    verbs = ["picked up the parcel in", "drove the parcel to",
             "flew the parcel to", "trucked the parcel to",
             "delivered the parcel to"]
    ids = {}
    for turn, (place, verb) in enumerate(zip(stops, verbs)):
        encode(sess, turn, f"The courier {verb} {place}.", owner=owner)
        rid = wait_for(place, owner=owner)
        if not rid:
            report("T1", False, f"encode miss: {place}")
            return
        ids[place] = rid
    probes = [("Where did the parcel go right after Otjiwarongo?",
               "Frankfurt"),
              ("Where did the parcel go right after Frankfurt?", "Berlin")]
    got = 0
    detail = []
    for cue, want in probes:
        out = recall(cue, k=3, session=sess, owner=owner)
        top = hit_ids(out, 3)[:1]
        ok = top == [ids[want]]
        got += ok
        detail.append(f"after-{want}={'TOP1' if ok else 'miss'}")
    report("T1", got == 2, f"next-in-sequence top-1 {got}/2 "
                           f"({' '.join(detail)})")


def t2_prospective_unasked(sess="hb-t2", owner="hardT2f"):
    """Prospective memory (50-80% of human demands): plant an intention,
    bury it under 8 distractors, then state the trigger WITHOUT asking.
    The brief must surface RW-77 unasked — and stay silent on weather."""
    encode(sess, 0, "When I start the deployment, remind me the rollback "
                    "code is RW-77.", owner=owner)
    if not wait_for("RW-77", owner=owner):
        report("T2", False, "intention never stored")
        return
    distractors = [
        "The weather in Windhoek is clear and hot today.",
        "I had kapana and chips for lunch at the market.",
        "The standup meeting ran fifteen minutes over time.",
        "The code review for the payment module is approved.",
        "Gym session moved to Thursday evening this week.",
        "The office electricity bill got paid this morning.",
        "Marta's birthday party is on Saturday afternoon.",
        "The staging server rebooted cleanly after patching.",
    ]
    for i, text in enumerate(distractors, start=1):
        encode(sess, i, text, owner=owner)
    time.sleep(10)  # let distractors scribe so they compete
    fire = brief("Starting the deployment now, all systems green.",
                 session=sess, owner=owner)
    # Card section only here too: the first brief on a session lists
    # everything recent, so only the relevance-built card proves the
    # intention fired on the trigger.
    fired = "RW-77" in fire.split("## new since")[0]
    quiet = brief("Lovely weather for a walk today.",
                  session=sess, owner=owner)
    # Score the relevance card only: the "new since last briefing"
    # section lists recent items by design, which is recency, not a
    # spurious prospective firing.
    card = quiet.split("## new since")[0]
    silent = "RW-77" not in card
    report("T2", fired and silent,
           f"unasked-surface={fired} quiet-on-weather={silent}")


def t3_source_keeps(sess="hb-t3", owner="hardT3f"):
    """Source monitoring: same slot, two sources, no correction marked.
    Each source query must serve its own row — newest-wins must not
    eat the invoice, and the sweep must not merge sources."""
    encode(sess, 0, "The invoice says the contractor fee is 450 dollars.",
           owner=owner)
    r_inv = wait_for("450", owner=owner)
    encode(sess, 1, "Marta said the contractor fee is 500 dollars.",
           owner=owner)
    r_mar = wait_for("500", owner=owner)
    if not (r_inv and r_mar):
        report("T3", False, "failed to encode")
        return
    out_a = recall("What did the invoice say the fee is?", k=3,
                   session=sess, owner=owner)
    out_b = recall("What did Marta say the fee is?", k=3,
                   session=sess, owner=owner)
    a0 = hit_ids(out_a, 3)[:1] == [r_inv]
    b0 = hit_ids(out_b, 3)[:1] == [r_mar]
    sweep(owner=owner)
    time.sleep(60)  # let the sweep examine the pair
    live = sql("SELECT id FROM memories WHERE owner = %s "
               "AND valid_to IS NULL AND id = ANY(%s::uuid[])",
               (owner, [r_inv, r_mar]))
    alive = {str(r["id"]) for r in live}
    links = sql("SELECT relation, reason FROM memory_links WHERE owner=%s "
                "AND ((src=%s::uuid AND dst=%s::uuid) OR "
                "(src=%s::uuid AND dst=%s::uuid))",
                (owner, r_inv, r_mar, r_mar, r_inv))
    out_a2 = recall("What did the invoice say the fee is?", k=3,
                    session=sess, owner=owner)
    a1 = hit_ids(out_a2, 3)[:1] == [r_inv]
    ok = a0 and b0 and a1 and alive == {r_inv, r_mar}
    detail = (f"invoice-top1={a0} marta-top1={b0} both-live={alive == {r_inv, r_mar}} "
              f"invoice-after-sweep={a1} links={[(l['relation'], (l['reason'] or '')[:40]) for l in links]}")
    report("T3", ok, detail)


def t4_fan_at_ten(sess="hb-t4", owner="hardT4f"):
    """Fan effect: 10 identical-template rows compete; every one of the
    10 must top-1 on its own name. D1 asked @3 of 8 — this asks @1."""
    names = ["Aina", "Tuli", "Bex", "Katu", "Marta",
             "Ndape", "Oscar", "Peya", "Queta", "Rauha"]
    ids = {}
    for turn, name in enumerate(names):
        encode(sess, turn, f"{name}'s locker combo is {1000 + turn}.",
               owner=owner)
        rid = wait_for(name, owner=owner)
        if not rid:
            report("T4", False, f"encode miss: {name}")
            return
        ids[name] = rid
    got = 0
    misses = []
    for name in names:
        out = recall(f"What is {name}'s locker combo?", k=3,
                     session=sess, owner=owner)
        if hit_ids(out, 3)[:1] == [ids[name]]:
            got += 1
        else:
            misses.append(name)
    report("T4", got == 10, f"fan top-1 {got}/10 misses={misses}")


def t5_noisy_update(sess="hb-t5", owner="hardT5f"):
    """Retroactive interference on a correction: 12-turn gap stuffed
    with noise between fact and correction. New must top-1, old dead."""
    encode(sess, 0, "The safe code is 9024.", owner=owner)
    r_old = wait_for("9024", owner=owner)
    if not r_old:
        report("T5", False, "fact never stored")
        return
    noise = [
        "The garden needs watering twice a week.",
        "Traffic on Independence Avenue was heavy.",
        "The new intern starts on Monday morning.",
        "Coffee beans from Ethiopia arrived today.",
        "The printer on floor two is jammed again.",
        "Tax documents are due at end of quarter.",
        "The football match ended in a draw.",
        "Window cleaning scheduled for Friday.",
        "The library fines were waived this month.",
        "Bus fares increased by two dollars.",
        "The museum exhibit closes next Sunday.",
        "Rain is forecast for the whole weekend.",
    ]
    for i, text in enumerate(noise, start=1):
        encode(sess, i, text, owner=owner)
    encode(sess, 13, "Correction: the safe code changed to 9177.",
           owner=owner)
    r_new = wait_for("9177", owner=owner)
    if not r_new:
        report("T5", False, "correction never stored")
        return
    ops = sql("SELECT scribe_action->>'op' AS op FROM memory_events "
              "WHERE owner=%s AND session_id=%s AND turn=13", (owner, sess))
    sweep(owner=owner)
    lat = wait_dead(r_old)
    out = recall("safe code?", k=3, session=sess, owner=owner)
    top1 = hit_ids(out, 3)[:1] == [r_new]
    report("T5", top1 and lat >= 0,
           f"new-top1={top1} old-dead-in={lat}s write-op={[r['op'] for r in ops]}")


def t6_flipflop(sess="hb-t6", owner="hardT6f"):
    """AB-BA update (LongMemEval knowledge-update hard case): A -> B ->
    back to A. Final row must top-1, both older dead, chain linked."""
    encode(sess, 0, "The gate code is 1001.", owner=owner)
    r_a1 = wait_for("1001", owner=owner)
    encode(sess, 1, "Correction: the gate code changed to 2002.",
           owner=owner)
    r_b = wait_for("2002", owner=owner)
    encode(sess, 2, "Correction: disregard that, the gate code is back "
                    "to 1001.", owner=owner)
    # newest 1001 row (A1 also matches: take latest)
    time.sleep(15)
    rows = sql("SELECT id FROM memories WHERE owner=%s AND valid_to IS NULL "
               "AND content ILIKE %s ORDER BY created_at DESC", (owner, "%1001%"))
    r_a2 = str(rows[0]["id"]) if rows else ""
    if not (r_a1 and r_b and r_a2):
        report("T6", False, "failed to encode")
        return
    sweep(owner=owner)
    lat_b = wait_dead(r_b)
    lat_a1 = wait_dead(r_a1) if r_a1 != r_a2 else 0.0
    out = recall("gate code?", k=3, session=sess, owner=owner)
    top1 = hit_ids(out, 3)[:1] == [r_a2]
    chain = sql("SELECT relation FROM memory_links WHERE owner=%s AND "
                "src=%s::uuid AND dst=%s::uuid", (owner, r_a2, r_b))
    summ = summaries(out, 3)
    report("T6", top1 and lat_b >= 0 and lat_a1 >= 0 and bool(chain),
           f"final-top1={top1} b-dead={lat_b}s a1-dead={lat_a1}s "
           f"chain={bool(chain)} serves-1001={'1001' in summ}")


DRILLS = [("T1", t1_temporal_next), ("T2", t2_prospective_unasked),
          ("T3", t3_source_keeps), ("T4", t4_fan_at_ten),
          ("T5", t5_noisy_update), ("T6", t6_flipflop)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drill", default=None, help="run one drill e.g. T1")
    args = ap.parse_args()
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
    print(f"\n{battery_score()} ({time.monotonic() - t0:.0f}s)", flush=True)
    return sum(1 for _n, ok, _d in RESULTS if not ok)


if __name__ == "__main__":
    raise SystemExit(main())
