"""NLI contradiction verifier (ONNX, zero torch).

Stage 2 of the write path: when an incoming turn is highly familiar to a
stored row, cosine alone cannot tell restatement from reversal (embeddings
encode topic, not stance — "X" vs "never X" scores ~0.85). The familiar row
becomes the premise, the turn the hypothesis; a DeBERTa-v3 NLI cross-encoder
labels the pair entailment / neutral / contradiction.

Weights live in the shared model cache (never in git) and auto-fetch on
first use, mirroring fastembed. Any load/inference failure raises NLIError
and the caller degrades OPEN (fall through to the LLM scribe): never lose
the turn because the verifier is missing. Label order is read from the
model's own config.json, never hardcoded.

Measured quirk (int8 quant): far-apart pairs ("sky is blue" vs "Ben drinks
coffee") read contradiction ~1.00. Harmless: the observer only forwards
pairs at cosine >= 0.80, where contra/entail/neutral all behave (>= 0.96).
"""
import json
import logging
import math
from pathlib import Path

import anyio

log = logging.getLogger("tottie.nli")

REPO = "Xenova/nli-deberta-v3-small"
MODEL_FILE = "onnx/model_int8.onnx"
NEED_FILES = [
    MODEL_FILE, "config.json", "tokenizer.json", "tokenizer_config.json",
    "special_tokens_map.json",
]
MAX_LEN = 256


class NLIError(Exception):
    pass


_session = None
_tokenizer = None
_id2label = None


def model_dir(settings) -> Path:
    if getattr(settings, "nli_model_dir", ""):
        return Path(settings.nli_model_dir)
    return Path(settings.embedding_cache_dir) / "nli-deberta-v3-small"


def _reset_for_tests() -> None:
    global _session, _tokenizer, _id2label
    _session = _tokenizer = _id2label = None


def _ensure_weights(d: Path) -> Path:
    model = d / MODEL_FILE
    if model.is_file() and (d / "tokenizer.json").is_file():
        return model
    log.info("nli weights missing; fetching %s", REPO)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise NLIError(f"huggingface_hub missing: {e}") from e
    try:
        snapshot_download(REPO, local_dir=str(d), allow_patterns=NEED_FILES)
    except Exception as e:
        raise NLIError(f"weight fetch failed: {type(e).__name__}: {e}") from e
    if not model.is_file():
        raise NLIError(f"fetch did not produce {MODEL_FILE}")
    return model


def _load(settings) -> None:
    global _session, _tokenizer, _id2label
    if _session is not None:
        return
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError as e:
        raise NLIError(f"nli stack missing: {e}") from e
    d = model_dir(settings)
    model = _ensure_weights(d)
    try:
        cfg = json.loads((d / "config.json").read_text())
        _id2label = {int(k): str(v).lower() for k, v in cfg["id2label"].items()}
    except (OSError, KeyError, ValueError) as e:
        raise NLIError(f"bad config.json: {e}") from e
    try:
        _tokenizer = Tokenizer.from_file(str(d / "tokenizer.json"))
        _tokenizer.enable_truncation(max_length=MAX_LEN)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        _session = ort.InferenceSession(
            str(model), sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
    except Exception as e:
        _session = _tokenizer = _id2label = None
        raise NLIError(f"load failed: {type(e).__name__}: {e}") from e
    log.info("nli ready: %s (%s)", REPO, model)


def _verify_sync(premise: str, hypothesis: str) -> dict:
    enc = _tokenizer.encode(premise, hypothesis)
    feed = {}
    for i in _session.get_inputs():
        if i.name == "input_ids":
            feed[i.name] = [enc.ids]
        elif i.name == "attention_mask":
            feed[i.name] = [enc.attention_mask]
        elif i.name == "token_type_ids":
            feed[i.name] = [enc.type_ids]
    try:
        (logits,) = _session.run(None, feed)
    except Exception as e:
        raise NLIError(f"inference failed: {type(e).__name__}: {e}") from e
    row = [float(x) for x in logits[0]]
    m = max(row)
    exps = [math.exp(x - m) for x in row]
    tot = sum(exps) or 1.0
    probs = {(_id2label.get(i, f"label_{i}")): exps[i] / tot
             for i in range(len(row))}
    label = max(probs, key=probs.get)
    return {
        "label": label,
        "p_contra": probs.get("contradiction", 0.0),
        "p_entail": probs.get("entailment", 0.0),
        "p_neutral": probs.get("neutral", 0.0),
    }


async def verify(premise: str, hypothesis: str, settings) -> dict:
    """NLI label for (stored premise, incoming hypothesis). Sync ONNX work
    runs off the event loop; raises NLIError when unusable."""
    _load(settings)
    return await anyio.to_thread.run_sync(_verify_sync, premise, hypothesis)
