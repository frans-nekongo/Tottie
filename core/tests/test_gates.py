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


def test_centroid_gate_is_gone():
    """The session-centroid surprise gate punished sustained topical work
    and died on dogfood night; familiarity-vs-store replaced it. This pins
    the removal so nobody resurrects the corpse."""
    assert not hasattr(gates, "surprise_score")
    assert not hasattr(gates, "first_turns_bypass")
    assert not hasattr(gates, "centroid")
