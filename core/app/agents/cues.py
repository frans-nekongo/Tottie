"""Rules-only cue classifier (zero model calls). First match wins; CORRECTION
beats everything (reconsolidation depends on it); CHITCHAT beats QUESTION
(full-string specific over ?-suffix general). Mirrors docs cue table.
Loss-cue statements (\"I lost my keys\") take the recall branch: the user is
asking the store, not telling it."""
import re
from dataclasses import dataclass, field

from .gates import is_chitchat

CORRECTION_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (r"\bactually\b", r"\bno wait\b", r"^\s*correction\s*:",
              r"\bi meant\b")
]
# NOTE (G4): bare "correction" mid-sentence ("method correction I was
# given") is meta-talk, not a correction act — it routed unrelated rows
# into the correction lane and superseded them. Only start-anchored
# "Correction: ..." marks now.
# Polarity-flip tripwire (G1 fix): explicit reversal ACTS. Fires ONLY
# inside the observer's familiar branch (a stored target exists), so bare
# commands ("kill the server" with no server memory) never misroute.
# Recall-oriented: false positives cost one LLM call, because the scribe +
# reconcile still compare objects and SKIP true restatements. Bare
# negations (don't/isn't/...) are DELIBERATELY absent: "Ben does not drink
# either" is an entailment and "Ben does not drink on weekdays" is a
# refinement — only the NLI arbiter judges those correctly (measured).
POLARITY_FLIP_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bnever\b", r"\bno longer\b", r"\bnot anymore\b",
        r"\bkill(?:ed|s|ing)?\b", r"\bremov(?:e|ed|al)\b",
        r"\bstop\b", r"\bundo\b", r"\brevert\b", r"\bcancel(?:led)?\b",
        r"\bdrop\b", r"\bdelet(?:e|ed|ion)\b",
        r"\bchanged?\b", r"\bmoved?\b", r"\bswitch(?:ed)?\b",
        r"\bwrong\b", r"\bincorrect\b", r"\bcontradict",
        r"\binstead\b",
    )
]


def polarity_flip(text: str) -> bool:
    return any(r.search(text) for r in POLARITY_FLIP_RES)
REFERENCE_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bthat\s+\w+",
        r"\bthe same\b",
        r"\bwe discussed\b",
        r"\byou mentioned\b",
    )
]
QUESTION_START_RE = re.compile(
    r"^(who|what|when|where|why|how|which)\b", re.IGNORECASE
)
COMMAND_VERBS = (
    "implement", "add", "fix", "create", "update", "refactor", "build",
    "write", "run", "show", "remind",
)
COMMAND_RE = re.compile(rf"^({'|'.join(COMMAND_VERBS)})\b", re.IGNORECASE)
LOSS_RE = re.compile(
    r"\b(lost|lose|losing|can't find|cannot find|missing|need\b|"
    r"where (is|are)|forgot)\b",
    re.IGNORECASE,
)
RECENCY_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bjust\b", r"\bso far\b", r"\blast \d+\b", r"\brecent\b",
        r"\blately\b", r"\bwhere were we\b", r"\brecap\b",
        r"\bwhat have we done\b", r"\bwhat did i\b", r"\bwhat have we\b",
    )
]
TAG_RE = re.compile(r"#([\w/-]+)")
MENTION_RE = re.compile(r"@([\w/-]+)")
QUOTED_RE = re.compile(r'"([^"]{1,80})"' r"|‘([^’]{1,80})’")
# Unicode letters (not [a-z]): coverage must see non-Latin scripts too.
# 3+ chars, digits excluded (codes come through tags/quotes, not prose).
WORD_RE = re.compile(r"[^\W\d_][^\W\d_/-]{2,}")
STOPWORDS = frozenset("""
what who when where why how which whose whom is are was were do does did
have has had the a an my your his her its our their of in on to for and or
but not with from that this these those then than so as at by be been am me
you we they it them us him her i just really very know tell give get got
""".split())
REMIND_RE = re.compile(r"\bremind me to\b(.+)", re.IGNORECASE)
REMIND_WHEN_RE = re.compile(r"\bwhen\b(.+)", re.IGNORECASE)
IN_DAYS_RE = re.compile(r"\bin (\d+) days?\b", re.IGNORECASE)
IN_HOURS_RE = re.compile(r"\bin (\d+) hours?\b", re.IGNORECASE)


@dataclass
class Cue:
    type: str  # CORRECTION|REFERENCE|QUESTION|COMMAND|CHITCHAT|STATEMENT
    entities: list[str] = field(default_factory=list)
    recall_cue: bool = False  # loss/need statement: ask the store, don't write
    replay: bool = False  # recency markers: ordered replay, not ranking
    policy: str = "general"  # general|command (assemble-to-act kit)


def coverage_entities(text: str) -> list[str]:
    """Content words for confidence coverage (separate from #/@/quote seeds,
    which drive retrieval legs and intention cues)."""
    return [w for w in dict.fromkeys(WORD_RE.findall(text.lower()))
            if w not in STOPWORDS]


def extract_entities(text: str) -> list[str]:
    found: list[str] = []
    found += [f"#{t}" for t in TAG_RE.findall(text)]
    found += [f"@{m}" for m in MENTION_RE.findall(text)]
    for a, b in QUOTED_RE.findall(text):
        found.append(a or b)
    seen, out = set(), []
    for e in found:
        if e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    return out


def classify(text: str) -> Cue:
    t = text.strip()
    entities = extract_entities(t)
    replay = any(r.search(t) for r in RECENCY_RES)
    if any(r.search(t) for r in CORRECTION_RES):
        return Cue("CORRECTION", entities, replay=replay)
    if any(r.search(t) for r in REFERENCE_RES):
        return Cue("REFERENCE", entities, replay=replay)
    # Full-string chitchat beats the ?-suffix: "hey, how are you?" is a
    # greeting, not a question (specific before general).
    if is_chitchat(t):
        return Cue("CHITCHAT", entities)
    if t.endswith("?") or QUESTION_START_RE.match(t):
        return Cue("QUESTION", entities, recall_cue=True, replay=replay)
    if COMMAND_RE.match(t):
        return Cue("COMMAND", entities, recall_cue=True, policy="command")
    cue = Cue("STATEMENT", entities, replay=replay)
    if LOSS_RE.search(t):
        cue.recall_cue = True  # "I lost my keys" wants the counter
    return cue


def parse_reminder(text: str) -> dict | None:
    """\"remind me to X [when Y] [tomorrow|in N days|in N hours]\" -> draft."""
    m = REMIND_RE.search(text.strip())
    if not m:
        return None
    rest = m.group(1).strip().rstrip(".")
    event_cue = None
    w = REMIND_WHEN_RE.search(rest)
    if w:
        event_cue = w.group(1).strip()
        rest = rest[: w.start()].strip().rstrip(",")
    days = hours = 0
    dm = IN_DAYS_RE.search(rest)
    hm = IN_HOURS_RE.search(rest)
    if dm:
        days = int(dm.group(1))
        rest = IN_DAYS_RE.sub("", rest).strip()
    elif hm:
        hours = int(hm.group(1))
        rest = IN_HOURS_RE.sub("", rest).strip()
    elif re.search(r"\btomorrow\b", rest, re.IGNORECASE):
        days = 1
        rest = re.sub(r"\btomorrow\b", "", rest, flags=re.IGNORECASE).strip()
    return {
        "content": re.sub(r"\s+", " ", rest).strip(" ,"),
        "event_cue": event_cue,
        "days": days,
        "hours": hours,
    }
