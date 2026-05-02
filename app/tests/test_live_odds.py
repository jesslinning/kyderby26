"""Tests for live odds HTML parsing (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.live_odds import (
    implied_win_probability,
    normalize_horse_name,
    parse_derby_entries_from_html,
    parse_fractional_odds,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "live_odds_derby_widget.html"


def test_normalize_horse_name():
    assert normalize_horse_name("  Right  To  Party ") == "RIGHT TO PARTY"


def test_parse_fractional_odds():
    assert parse_fractional_odds("5/1") == (5, 1)
    assert parse_fractional_odds(" 9/2 ") == (9, 2)
    assert parse_fractional_odds("bad") is None


def test_implied_win_probability():
    assert implied_win_probability((5, 1)) == pytest.approx(1 / 6)


def test_parse_fixture_widget():
    html = _FIXTURE.read_text(encoding="utf-8")
    rows = parse_derby_entries_from_html(html)
    assert len(rows) == 2
    assert rows[0]["horse_name"] == "Renegade"
    assert rows[0]["horse_name_normalized"] == "RENEGADE"
    assert rows[0]["odds_str"] == "5/1"
    assert rows[0]["implied_probability"] == pytest.approx(0.166667, abs=1e-6)
    assert rows[0]["market_strength"] == 1.0  # favorite
    assert rows[1]["horse_name"] == "Albus"
    assert rows[1]["market_strength"] == 0.0  # longshot
