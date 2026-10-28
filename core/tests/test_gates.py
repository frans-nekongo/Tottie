"""Gates are pure math + rules: fixed vectors, exact expectations, no LLM."""
from app.agents import gates


def test_chitchat_pattern():
    for t in ("thanks!", "Hi", "ok.", "cool", "THANK YOU"):
        assert gates.is_chitchat(t), t
    for t in ("My name is Ann.", "I lost my keys", "thanks for nothing much"):
        assert not gates.is_chitchat(t), t


def test_chitchat_greeting_combos():
    # R1: "hey, how are you?" cost a 4.4s LLM call that also skipped.
    for t in ("How are you?", "hey, how are you?", "Hey how's it going"):
        assert gates.is_chitchat(t), t
    for t in ("hey I lost my keys", "hi Ann, my name is Bo", "how are you funding this"):
        assert not gates.is_chitchat(t), t


def test_cosine_basics():
    assert gates.cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert gates.cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert gates.cosine([1.0, 0.0], [-1.0, 0.0]) == -1.0
    assert gates.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_surprise_centroid_math():
    recent = [[1.0, 0.0], [0.0, 1.0]]
    # identical to centroid direction -> low surprise
    score, passed = gates.surprise_score([1.0, 1.0], recent, floor=0.20)
    assert score < 0.01 and passed is False
    # orthogonal-ish to centroid -> high surprise
    score, passed = gates.surprise_score([-1.0, -1.0], recent, floor=0.20)
    assert score > 0.9 and passed is True
    # no history: always passes with full score
    score, passed = gates.surprise_score([1.0, 0.0], [], floor=0.20)
    assert (score, passed) == (1.0, True)


def test_first_turns_bypass():
    assert gates.first_turns_bypass(0) is True
    assert gates.first_turns_bypass(2) is True
    assert gates.first_turns_bypass(3) is False
