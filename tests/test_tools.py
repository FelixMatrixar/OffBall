"""The OffBall MCP tools, on the showcase match (no model needed)."""

from __future__ import annotations

import pytest

from offball.mcp import tools as T


@pytest.fixture(scope="module")
def goal_card():
    goal = next(c for c in T.list_candidates("m07") if c["period"] == 2 and c["creator_id"] == "kes-09")
    return T.moment_card("m07", goal["candidate_id"])


def test_moment_card(goal_card) -> None:
    card = goal_card
    assert card["outcome"] == "goal"
    assert card["creator"]["number"] == 9 and card["dragged"][0]["player_id"] == "ash-05"
    keys = [b["key"] for b in card["beats"]]
    assert keys[0] == "run_start" and "pass_into_gap" in keys and keys[-1] == "goal"
    assert set(card["anchors"]) >= {"run", "gap", "defender", "pass"}


def test_compute_metric_is_exact() -> None:
    r = T.compute_metric("m07", "displacement_m", {"player_id": "ash-05", "period": 2, "t_start_ms": 1239560,
                                                   "t_end_ms": 1243560})
    assert r["unit"] == "m" and r["value"] == 15.1 and r["evidence_ids"]


def test_viewer_clock_blocks_the_future(goal_card) -> None:
    token = T.VIEWER_CLOCK.set((2, goal_card["t_start_ms"] - 1000))
    try:
        assert all(c["t_end_ms"] < goal_card["t_start_ms"] for c in T.list_candidates("m07", period=2))
        with pytest.raises(ValueError, match="hasn't happened yet"):
            T.events_between("m07", 2, 1_240_000, 1_245_000)
    finally:
        T.VIEWER_CLOCK.reset(token)


def test_evidence_resolves() -> None:
    ev = T.get_evidence("m07", ["m07-e1335", "m07-f2-31000", "nonsense"])
    assert ev["m07-e1335"]["type"] == "shot"
    assert 20 <= len(ev["m07-f2-31000"]["players"]) <= 22  # Kestrel Bay are down to ten by then
    assert "error" in ev["nonsense"]
