"""Deterministic gates: heuristic prefilter, attention, surprise. Pure math and
rules — no LLM. Mirrors the frozen cue-table chitchat pattern."""
import math
import re

CHITCHAT_RE = re.compile(
    r"^(thanks|thank you|hi|hello|hey|bye|ok|okay|cool|great)[!.]*$",
    re.IGNORECASE,
)

FIRST_TURNS_ALWAYS_LAND = 3


def is_chitchat(text: str) -> bool:
    return bool(CHITCHAT_RE.match(text.strip()))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def centroid(vecs: list[list[float]]) -> list[float]:
    n = len(vecs)
    dim = len(vecs[0])
    return [sum(v[i] for v in vecs) / n for i in range(dim)]


def surprise_score(
    turn_vec: list[float], recent_vecs: list[list[float]], floor: float
) -> tuple[float, bool]:
    """Novelty = 1 - cos(turn, centroid of recent turns). With no history there
    is nothing to be unsurprising against: score 1.0, always passes."""
    if not recent_vecs:
        return 1.0, True
    score = max(0.0, min(1.0, 1.0 - cosine(turn_vec, centroid(recent_vecs))))
    return score, score >= floor


def first_turns_bypass(session_event_count: int) -> bool:
    """First real facts always land: new sessions skip the surprise floor."""
    return session_event_count < FIRST_TURNS_ALWAYS_LAND
