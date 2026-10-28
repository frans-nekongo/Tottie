"""Deterministic gates: heuristic prefilter + vector math. Pure math and
rules — no LLM. Mirrors the frozen cue-table chitchat pattern.

The session-centroid surprise gate lived here until dogfood night proved it
punished sustained topical work (it dropped the night's most important fact
at 0.25-vs-centroid while 0.68-novel-vs-store). The gate is now familiarity
against the STORE (observer._familiarity): the brain compares input to
memory, never to recent chatter.
"""
import math
import re

CHITCHAT_RE = re.compile(
    r"^(thanks|thank you|hi|hello|hey|bye|ok|okay|cool|great|"
    r"how are you|how's it going)[?!.]*$",
    re.IGNORECASE,
)
# "hey, how are you?" — strip one leading greeting so combos still match.
_GREET_PREFIX_RE = re.compile(r"^(hi|hello|hey)[,.]?\s+", re.IGNORECASE)


def is_chitchat(text: str) -> bool:
    t = _GREET_PREFIX_RE.sub("", text.strip()).strip()
    return bool(CHITCHAT_RE.match(t or text.strip()))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))
