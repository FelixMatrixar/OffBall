"""Panel numbers (INTEGRATION.md 6.5): computed from the observed match, in the frontend's shapes."""

from __future__ import annotations

import httpx
import pytest

from offball.mcp import tools as T
from offball.services import stats as S
from offball.services.api import app

UNTIL = (2, 1_091_500)  # the end of the showcase moment
WINDOW = ((2, 1_080_000), UNTIL)


@pytest.fixture(scope="module")
def md():
    return T.REGISTRY.data("m07")


@pytest.fixture(scope="module")
def cands():
    return T.REGISTRY.candidates("m07")


def test_match_series_have_the_frontends_shapes(md) -> None:
    mom = S.momentum(md, UNTIL)
    assert [r["minute"] for r in mom] == list(range(64)) and all(-1 <= r["value"] <= 1 for r in mom)
    ctl = S.control_index(md, UNTIL)
    assert len(ctl) == 64 and all(set(r) == {"minute", "kes", "ash"} and 0 <= r["kes"] <= 100 for r in ctl)
    shape = S.shape(md, UNTIL)
    assert [r["minute"] for r in shape] == list(range(0, 65, 5))
    assert set(shape[0]) == {"minute", "ashLine", "ashWidth", "ashCompact", "kesPress"}
    net = S.pass_network(md, UNTIL)
    assert {n["id"][:3] for n in net["nodes"]} == {"kes"} and all(e["n"] >= 3 for e in net["edges"])
    assert all(0 <= n["x"] <= 105 and 0 <= n["y"] <= 68 for n in net["nodes"])


def test_player_numbers_count_only_what_had_happened(md, cands) -> None:
    f = S.focus(md, cands, "kes-09", WINDOW)
    assert set(f) == {"runs", "dragged", "space", "sprints", "distanceKm", "topSpeed", "runsByType"}
    assert f["runs"][1] == f["runs"][0] + 1, "the showcase decoy run happens inside the moment"
    assert f["space"][1] > f["space"][0] and 0 < f["space"][2] < 11.5
    assert 0 < f["distanceKm"] < 12 and 20 < f["topSpeed"] < 40
    grid = S.occupancy(md, "kes-09", UNTIL)
    assert len(grid) == 21 * 14 and abs(sum(grid) - 64) < 2, "minutes on the pitch up to 63:11"
    assert S.distance_series(md, "kes-09", UNTIL)[0]["metres"] > 300
    assert any(r["minute"] == 63 and r["type"] == "Decoy" for r in S.run_map(md, cands, "kes-09", UNTIL))
    leaders = S.leaders(md, cands, UNTIL)
    assert leaders[0]["id"] == "kes-09" and leaders[0]["lo"] <= leaders[0]["v"] <= leaders[0]["hi"]


async def test_the_api_serves_stats_and_says_when_it_cant() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/matches/m07/stats/control_index", params={"period": 2, "t_ms": 1_091_500})
        assert r.status_code == 200 and len(r.json()) == 64
        r = await client.get("/api/matches/m07/stats/focus",
                             params={"player_id": "kes-09", "period": 2, "t_ms": 1_091_500, "from_ms": 1_080_000})
        assert r.status_code == 200 and r.json()["runs"][2] > 0
        assert (await client.get("/api/matches/m07/stats/focus")).status_code == 404
        assert (await client.get("/api/matches/m07/stats/nope")).status_code == 404
