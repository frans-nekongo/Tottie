"""CLI unit tests: pure helpers only (no server). The verbs are thin HTTP
wrappers verified live; importing the module must not touch the real env."""
import importlib.util
import os
from pathlib import Path

CLI = (Path(__file__).resolve().parent.parent / "scripts" / "tottie.py")


def _load():
    spec = importlib.util.spec_from_file_location("tottie_cli", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_import_is_side_effect_free(monkeypatch):
    monkeypatch.delenv("TOTTIE_CLI_PROBE_XYZ", raising=False)
    mod = _load()
    assert "TOTTIE_CLI_PROBE_XYZ" not in os.environ
    assert hasattr(mod, "_load_dotenv")


def test_dotenv_fills_missing_only(tmp_path, monkeypatch):
    mod = _load()
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n"
        "TOTTIE_CLI_A=from-file\n"
        'TOTTIE_CLI_B="quoted value"\n'
        "TOTTIE_CLI_C=from-file\n"
        "NOT_A_PAIR\n"
        "\n"
    )
    monkeypatch.delenv("TOTTIE_CLI_A", raising=False)
    monkeypatch.delenv("TOTTIE_CLI_B", raising=False)
    monkeypatch.setenv("TOTTIE_CLI_C", "from-env")
    mod._load_dotenv(f)
    assert os.environ["TOTTIE_CLI_A"] == "from-file"
    assert os.environ["TOTTIE_CLI_B"] == "quoted value"
    assert os.environ["TOTTIE_CLI_C"] == "from-env"  # env wins
    assert "NOT_A_PAIR" not in os.environ


def test_dotenv_missing_file_is_silent(tmp_path):
    mod = _load()
    mod._load_dotenv(tmp_path / "nope.env")  # must not raise


def test_injection_orders_context_before_task():
    mod = _load()
    out = mod._injection(
        "Owner is Frans.",
        [{"tier": "knowledge", "kind": "fact",
          "summary": "Fee is N$360.", "tags": ["nust"],
          "why": "vector #1"}],
        "What is the fee?",
    )
    assert out.index("# memory context") < out.index("# task")
    assert "Owner is Frans." in out
    assert "Fee is N$360." in out and "#nust" in out
    assert out.rstrip().endswith("What is the fee?")


def test_injection_empty_parts_stay_explicit():
    mod = _load()
    out = mod._injection("  ", [], "Do the thing.")
    assert "(no ambient context)" in out
    assert "(nothing recalled)" in out
    assert "# task\nDo the thing." in out


def test_injection_caps_brief_flood():
    mod = _load()
    flood = "\n".join(f"- row {i}" for i in range(100))
    out = mod._injection(flood, [], "Task.", brief_lines=10)
    assert "- row 9" in out and "- row 10" not in out
    assert "(90 more)" in out


def test_split_queries_numbered_and_single():
    mod = _load()
    parts = mod._split_queries(
        "Answer: (1) NUST fee and deadline. (2) April breach malware.")
    assert len(parts) == 2 and parts[0].startswith("NUST")
    assert mod._split_queries("What is the fee schedule?") == [
        "What is the fee schedule?"]
    qs = mod._split_queries("What is the full fee? When does it close?")
    assert len(qs) == 2


def test_interleave_favors_all_parts_equally():
    mod = _load()
    a = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
    b = [{"id": "b1"}, {"id": "b2"}]
    out = mod._interleave([a, b], 4)
    assert [h["id"] for h in out] == ["a1", "b1", "a2", "b2"]
    dup = mod._interleave([a, [{"id": "a1"}, {"id": "b9"}]], 4)
    assert [h["id"] for h in dup] == ["a1", "a2", "b9", "a3"]
