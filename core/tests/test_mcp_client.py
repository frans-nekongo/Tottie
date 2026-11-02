"""mcp_client argv tests: pure parse_cli only (no MCP server). A
positional-only client once sent the literal string "--owner" as a
recall query and its mush was misread as a retrieval regression:
unknown flags must exit loud, never become the query."""
import importlib.util
from pathlib import Path

import pytest

CLIENT = (Path(__file__).resolve().parent.parent.parent
          / "dev-ref" / "mcp_client.py")


def _load():
    spec = importlib.util.spec_from_file_location("mcp_client", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_positional_legacy_shape():
    parse = _load().parse_cli
    assert parse(["mcp_client.py", "recall", "what is the fee"]) == (
        "recall", {"query": "what is the fee", "session_id": "dev-ref-1"})
    assert parse(["mcp_client.py", "brief", "fix it", "s1", "9"]) == (
        "brief", {"session_id": "s1", "since_event_id": 9, "text": "fix it"})


def test_flags_shape_with_aliases_and_ints():
    parse = _load().parse_cli
    cmd, args = parse(["mcp_client.py", "recall", "--query", "fee",
                       "--session", "s2", "--k", "12"])
    assert cmd == "recall"
    assert args == {"query": "fee", "session_id": "s2", "k": 12}
    cmd, args = parse(["mcp_client.py", "brief", "--text", "t",
                       "--since_event_id", "3"])
    assert args["since_event_id"] == 3
    assert args["session_id"] == "dev-ref-1"


def test_unknown_flag_is_loud_never_the_query():
    parse = _load().parse_cli
    with pytest.raises(ValueError, match="unknown flag --owner"):
        parse(["mcp_client.py", "recall", "--owner", "owner_local",
               "--query", "what is the fee"])
    with pytest.raises(ValueError, match="must not mix"):
        parse(["mcp_client.py", "recall", "fee", "--k", "5"])
    with pytest.raises(ValueError, match="recall needs --query"):
        parse(["mcp_client.py", "recall", "--k", "5"])
    with pytest.raises(ValueError, match="needs an integer"):
        parse(["mcp_client.py", "recall", "--query", "q", "--k", "many"])
