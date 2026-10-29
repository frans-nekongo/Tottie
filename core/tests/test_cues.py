"""Cue table contract: first match wins, CORRECTION beats all, loss-cues and
recency markers route correctly. Pure rules — no DB, no LLM."""
from app.agents.cues import classify, extract_entities, parse_reminder


def test_correction_beats_everything():
    assert classify("Actually, implement feature A").type == "CORRECTION"
    assert classify("No wait, what did we decide?").type == "CORRECTION"
    assert classify("I meant the other one").type == "CORRECTION"


def test_reference():
    assert classify("Use that approach again").type == "REFERENCE"
    assert classify("Do the same as yesterday").type == "REFERENCE"
    assert classify("Like we discussed in March").type == "REFERENCE"


def test_question():
    assert classify("When is her birthday again?").type == "QUESTION"
    assert classify("What did we decide").type == "QUESTION"
    assert classify("How do I deploy this").type == "QUESTION"


def test_command_policy():
    c = classify("Implement feature A for #project/A")
    assert c.type == "COMMAND" and c.policy == "command"
    assert classify("Fix the login bug").type == "COMMAND"
    assert classify("Remind me to water the plants").type == "COMMAND"


def test_chitchat_mirrors_gates():
    assert classify("thanks!").type == "CHITCHAT"
    assert classify("hey, how are you?").type == "CHITCHAT"


def test_statement_default_and_loss_cue():
    assert classify("The sky is blue.").type == "STATEMENT"
    c = classify("I lost my keys")
    assert c.type == "STATEMENT" and c.recall_cue is True
    c = classify("I can't find the deploy notes")
    assert c.recall_cue is True
    assert classify("The sky is blue.").recall_cue is False


def test_replay_markers():
    assert classify("Where were we?").replay is True
    assert classify("What did I just do").replay is True
    assert classify("Recap so far").replay is True
    assert classify("What is my name").replay is False
    assert classify("What have we talked about?").replay is True
    assert classify("What have we talked about?").type == "QUESTION"


def test_entities():
    assert extract_entities('Ship #project/A with @frans "Friday"') == [
        "#project/A", "@frans", "Friday",
    ]
    assert extract_entities("nothing here") == []


def test_word_pattern_sees_unicode():
    """Coverage words are unicode letters: German compounds and non-Latin
    scripts match (digits still excluded)."""
    from app.agents.cues import WORD_RE

    words = WORD_RE.findall("Wie lautet der Tresorcode?")
    assert "Tresorcode" in words and "lautet" in words, words
    # spaceless scripts match whole runs (seen, not segmented — splitting
    # CJK needs a real segmenter, a documented residual)
    assert WORD_RE.findall("ビールが飲みたい") == ["ビールが飲みたい"]
    assert WORD_RE.findall("code 1111") == ["code"]


def test_entities_see_unicode():
    """Tags are unicode-aware; a non-English ? question still classifies."""
    assert "#café" in extract_entities("Meet at #café tomorrow")
    q = classify("Wie lautet der Tresorcode?")
    assert q.type == "QUESTION" and q.recall_cue is True


def test_parse_reminder():
    d = parse_reminder("Remind me to water the plants tomorrow")
    assert d and d["content"] == "water the plants" and d["days"] == 1
    d = parse_reminder("remind me to call Ann in 3 days")
    assert d and d["content"] == "call Ann" and d["days"] == 3
    d = parse_reminder("remind me to stretch when I stand up")
    assert d and d["content"] == "stretch" and d["event_cue"] == "I stand up"
    assert parse_reminder("just a sentence") is None
