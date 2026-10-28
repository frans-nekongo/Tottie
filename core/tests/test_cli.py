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
