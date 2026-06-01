"""chatterbox_generate.split_text — splits long narration into TTS-friendly chunks."""

from __future__ import annotations

from chatterbox_generate import split_text


def test_split_text_short():
    result = split_text("Hello world.", max_chars=500)
    assert len(result) == 1
    assert result[0] == "Hello world."


def test_split_text_long():
    text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
    result = split_text(text, max_chars=40)
    assert len(result) > 1
    joined = " ".join(result)
    assert "First sentence" in joined
    assert "Fifth sentence" in joined


def test_split_text_empty():
    result = split_text("", max_chars=500)
    assert len(result) == 1


def test_split_text_single_long_sentence():
    text = "A" * 600
    result = split_text(text, max_chars=500)
    assert len(result) >= 1
