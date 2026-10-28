"""Observer+Scribe in ONE shared LLM call: score salience, propose candidates.

Flow: heuristic skip -> embed turn -> surprise gate (first-3 bypass) -> single
structured-output call -> validate -> persist. Any LLM failure degrades to a RAW
episodic row flagged needs_curation: never lose the turn, never fake structure.
LLM latency + token usage ride on the Observation into the event ledger.
"""
import json
import logging
import time

from pydantic import BaseModel, Field, ValidationError

from ..config import Settings
from ..providers.base import ProviderError
from ..providers.resolve import resolve_provider
from . import gates

log = logging.getLogger("tottie.observer")

SYSTEM = """You are Tottie's Observer+Scribe. Read one conversation turn and decide what, if anything, is worth remembering.
Respond with JSON ONLY, exactly this shape, no fences, no prose:
{"keep": bool, "salience": 0.0-1.0, "candidates": [{"kind": "identity|convention|decision|lesson|preference|event", "subject": str|null, "predicate": str|null, "object": str|null, "content": str, "tags": [str], "principle": str|null}]}
Rules: keep=false for greetings, thanks, and smalltalk. salience = will-this-matter-later from 0 to 1. content = the durable fact in one sentence. tags = lowercase topic words. principle = the general rule if the turn states one, else null. Never invent facts not in the turn."""

KIND_TO_TIER = {
    "identity": "identity",
    "convention": "knowledge",
    "decision": "knowledge",
    "lesson": "procedural",
    "preference": "knowledge",
    "event": "episodic",
}


class Candidate(BaseModel):
    kind: str = "event"
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    principle: str | None = None


class ScribeOutput(BaseModel):
    keep: bool = False
    salience: float = Field(default=0.0, ge=0.0, le=1.0)
    candidates: list[Candidate] = Field(default_factory=list)


class Observation:
    def __init__(
        self,
        *,
        keep: bool,
        salience: float,
        surprise: float,
        candidates: list[dict],
        verdict: str,
        provider: str,
        raw_fallback: bool = False,
        latency_ms: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self.keep = keep
        self.salience = salience
        self.surprise = surprise
        self.candidates = candidates
        self.verdict = verdict
        self.provider = provider
        self.raw_fallback = raw_fallback
        self.latency_ms = latency_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _parse_output(text: str) -> ScribeOutput:
    return ScribeOutput.model_validate_json(_strip_fences(text))


def _raw_observation(text: str, salience: float, surprise: float, reason: str) -> Observation:
    return Observation(
        keep=True,
        salience=salience,
        surprise=surprise,
        candidates=[
            {
                "kind": "event",
                "tier": "episodic",
                "subject": None,
                "predicate": None,
                "object": None,
                "content": text,
                "tags": [],
                "principle": None,
            }
        ],
        verdict=f"RAW ({reason})",
        provider="none",
        raw_fallback=True,
    )


async def observe(*, db, embedder, turn, settings: Settings) -> Observation:
    text = turn.text.strip()
    if gates.is_chitchat(text):
        return Observation(
            keep=False, salience=0.0, surprise=0.0, candidates=[],
            verdict="heuristic: chitchat", provider="none",
        )
    vec, _ = await embedder.embed(text)
    recent = await db.fetch(
        "SELECT utterance AS t FROM memory_events "
        "WHERE session_id = %s AND utterance IS NOT NULL "
        "ORDER BY id DESC LIMIT 10",
        (turn.session_id,),
    )
    recent_vecs = []
    for r in recent:
        v, _ = await embedder.embed(r["t"])
        recent_vecs.append(v)
    score, passed = gates.surprise_score(vec, recent_vecs, settings.surprise_floor)
    count = await db.fetchval(
        "SELECT count(*) FROM memory_events WHERE session_id = %s", (turn.session_id,)
    )
    if gates.first_turns_bypass(count or 0):
        passed = True
    if not passed:
        return Observation(
            keep=False, salience=0.0, surprise=score, candidates=[],
            verdict=f"surprise {score:.2f} < {settings.surprise_floor:.2f}",
            provider="none",
        )
    prompt_tokens = completion_tokens = 0
    resampled = False
    t0 = time.monotonic()
    try:
        provider = await resolve_provider()
    except Exception as e:
        log.warning("no provider (%s); raw fallback", e)
        return _raw_observation(text, 0.5, score, "no provider")
    try:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Turn:\n{text}"},
        ]
        # 2048 floor (R1): the reasoning model hit finish=length with empty
        # content on 2/6 live turns at 1024. Cap only pays when needed.
        try:
            raw = await provider.complete(
                messages, max_tokens=2048, json_object=True
            )
        except ProviderError as e:
            if "finish=length" not in str(e):
                raise
            # Reasoning spiral (R1: same input fails then succeeds on
            # resample). One identical retry; tokens burned by the dead
            # attempt are uncountable (the error carries no usage).
            log.info("length-finish on first sample; resampling once")
            raw = await provider.complete(
                messages, max_tokens=2048, json_object=True
            )
            resampled = True
        prompt_tokens += raw.prompt_tokens
        completion_tokens += raw.completion_tokens
        try:
            out = _parse_output(raw.text)
        except (ValidationError, ValueError):
            repair = await provider.complete(
                messages
                + [
                    {"role": "assistant", "content": raw.text},
                    {
                        "role": "user",
                        "content": "That was not valid JSON. Reply with ONLY the JSON object, no fences, no prose.",
                    },
                ],
                max_tokens=2048,
                json_object=True,
            )
            prompt_tokens += repair.prompt_tokens
            completion_tokens += repair.completion_tokens
            out = _parse_output(repair.text)
    except Exception as e:
        log.warning("observe LLM failed (%s); raw fallback", e)
        return _raw_observation(text, 0.5, score, "llm failed")
    finally:
        await provider.close()
    latency_ms = int((time.monotonic() - t0) * 1000)
    salience = out.salience
    if turn.trust == "user_direct" and any(c.kind == "identity" for c in out.candidates):
        salience = max(salience, settings.identity_salience)
    if not out.keep:
        return Observation(
            keep=False, salience=salience, surprise=score, candidates=[],
            verdict=f"model keep=false sal={salience:.2f}"
            + (" resampled" if resampled else ""), provider=provider.name,
            latency_ms=latency_ms, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    cands = out.candidates or [Candidate(kind="event", content=text)]
    if not out.candidates:
        log.info("keep=true with no candidates; persisting whole turn as event")
    structured = [
        {
            "kind": c.kind if c.kind in KIND_TO_TIER else "event",
            "tier": KIND_TO_TIER.get(c.kind, "episodic"),
            "subject": c.subject,
            "predicate": c.predicate,
            "object": c.object,
            "content": c.content or text,
            "tags": [t for t in c.tags if isinstance(t, str)][:12],
            "principle": c.principle,
        }
        for c in cands
    ]
    return Observation(
        keep=True, salience=salience, surprise=score, candidates=structured,
        verdict=f"keep sal={salience:.2f} sur={score:.2f} n={len(structured)}"
        + (" resampled" if resampled else ""),
        provider=provider.name, latency_ms=latency_ms,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
    )
