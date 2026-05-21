"""Unit tests for the per-line speech metrics accumulator."""
from __future__ import annotations

from digital_actor.stage import _SpeechMetrics


def test_summary_after_single_chunk(monkeypatch) -> None:
    """A single first+final chunk produces a coherent summary."""
    clock = iter([0.0, 0.250])
    monkeypatch.setattr(
        "digital_actor.stage.time.monotonic", lambda: next(clock)
    )
    m = _SpeechMetrics(line_id="abc", sample_rate=24000)
    m.record_chunk(num_bytes=4800, is_final=True)
    s = m.summarize()
    assert s["line_id"] == "abc"
    assert s["chunks"] == 1
    assert s["bytes"] == 4800
    assert s["sample_rate"] == 24000
    assert s["t_first_ms"] == 0
    assert s["elapsed_s"] == 0.250
    assert s["max_gap_ms"] == 0


def test_summary_after_many_chunks(monkeypatch) -> None:
    """Inter-chunk produce gaps and totals are tracked correctly."""
    # clock values: first chunk produced at t=0.0, then t=0.05, t=0.30 (big gap),
    # t=0.32 (final).
    clock = iter([0.0, 0.05, 0.30, 0.32])
    monkeypatch.setattr(
        "digital_actor.stage.time.monotonic", lambda: next(clock)
    )
    m = _SpeechMetrics(line_id="line", sample_rate=24000)
    m.record_chunk(num_bytes=1000, is_final=False)
    m.record_chunk(num_bytes=1000, is_final=False)
    m.record_chunk(num_bytes=1000, is_final=False)
    m.record_chunk(num_bytes=0, is_final=True)
    s = m.summarize()
    assert s["chunks"] == 4
    assert s["bytes"] == 3000
    assert s["t_first_ms"] == 0
    # Biggest produce gap is between chunk 2 (t=0.05) and chunk 3 (t=0.30) = 250 ms.
    assert s["max_gap_ms"] == 250
    assert s["elapsed_s"] == 0.320


def test_chunk_delta_ms(monkeypatch) -> None:
    """`record_chunk` returns ms elapsed since the previous chunk."""
    clock = iter([0.0, 0.040, 0.090])
    monkeypatch.setattr(
        "digital_actor.stage.time.monotonic", lambda: next(clock)
    )
    m = _SpeechMetrics(line_id="x", sample_rate=24000)
    d0 = m.record_chunk(num_bytes=10, is_final=False)
    d1 = m.record_chunk(num_bytes=10, is_final=False)
    d2 = m.record_chunk(num_bytes=0, is_final=True)
    assert d0 == 0
    assert d1 == 40
    assert d2 == 50
