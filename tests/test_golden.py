"""The golden render tests: a stream that airs each case the way the frontend expects passes, and each way of
getting it wrong fails the check that covers it."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from offball.core import FRAME_MS, frame_ref
from offball.eval import golden
from offball.models.match_data import MatchData

LABELS = ["synthetic-data", "ai-generated"]


def _overlay(exp: dict, n: int, kind: str, mode: str, t0: int, t1: int, anchors: dict, evidence: list[str],
             group: str, data: dict | None = None, text: str = "") -> dict:
    return {"schema_version": "2.0", "overlay_id": f"{exp['match_id']}-o{n:04d}", "rev": 1, "match_id": exp["match_id"],
            "period": exp["period"], "t_start_ms": t0, "t_end_ms": t1, "kind": kind,
            "layer": "dom" if kind in ("caption", "stat_card") else "pitch", "priority": 1, "mode": mode,
            "anchors": anchors, "text": {"en": text} if text else {}, "speech": {}, "a11y_text": {"en": kind},
            "data": data or {}, "evidence_ids": evidence, "confidence": 0.9, "approval": "auto",
            "counterfactual_id": None, "detected_moment_id": group, "ai_generated": True, "labels": list(LABELS)}


def _graphics(exp: dict, md: MatchData) -> list[dict]:
    """Every graphic a good pipeline would send for the case's planted moments."""
    out: list[dict] = []
    for g, mom in enumerate(m for m in exp["moments"] if m.get("must_air")):
        group = f"live-{g + 1:04d}"
        t0, t1 = mom["t_start_ms"], mom["t_end_ms"]
        mid = max(t0 + 2500, (t0 + t1) // 2)
        at = frame_ref(md.match_id, exp["period"], t0 // FRAME_MS)
        cites = [at] + ([mom["pass"]["event_id"]] if "pass" in mom else [])
        for mode in exp["modes"]:
            def add(kind, a, b, anchors, data=None, text="", mode=mode, cites=cites, group=group):
                out.append(_overlay(exp, len(out) + 1, kind, mode, a, b, anchors, cites, group, data, text))

            add("caption", t0, t1, {}, text=f"{mom['creator_id']} makes the {mom['type'].replace('_', ' ')}.")
            if "run_arrow" in mom["required_kinds"]:
                path = mom["run"]["path"]
                start = min(path, key=lambda p: abs(p[0] - t0))
                end = max(path[path.index(start):], key=lambda p: np.hypot(p[1] - start[1], p[2] - start[2]))
                add("run_arrow", t0, mid, {"player_id": mom["creator_id"], "from_xy": start[1:], "to_xy": end[1:]},
                    {"lead_s": 0.8})
            if "gap_ring" in mom["required_kinds"]:
                add("gap_ring", mid, t1 + 1500, {"centre_xy": mom["gap"]["centre_xy"],
                                                 "radius_m": mom["gap"]["radius_m"]}, {"live": "gap_zone"})
            if "pass" in mom and mode in ("analyst", "broadcaster"):
                add("pass_line", mid, mid + 2500, {"player_ids": mom["pass"]["player_ids"]},
                    {"distance_m": mom["pass"]["distance_m"]})
        if mom["dragged_ids"]:
            pf, d = md.periods[exp["period"]], mom["dragged_ids"][0]
            f0, f1 = t0 // FRAME_MS, mid // FRAME_MS
            col = md.players.index(d)
            moved = float(np.hypot(*(pf.xy[pf.index_of(f1 * FRAME_MS), col] - pf.xy[pf.index_of(f0 * FRAME_MS), col])))
            out.append(_overlay(exp, len(out) + 1, "stat_card", "broadcaster", mid, mid + 3000, {"player_id": d},
                                [frame_ref(md.match_id, exp["period"], f) for f in (f0, f1)], group,
                                {"value": round(moved, 1), "unit": "m"}, "DEFENDER PULLED"))
    return out


def _stream(name: str, graphics: list[dict] | None = None) -> list[dict]:
    """The case's frames and score as the feed has them, a clock.sync every second, and each graphic sent 2 s
    before it is due."""
    exp = golden.load_case(name)
    md = golden._match_data(exp["set"], exp["match_id"])
    graphics = _graphics(exp, md) if graphics is None else graphics
    feed = golden.load_stream(golden.DATASETS / "golden" / name / "feed.jsonl")
    due = sorted(graphics, key=lambda o: o["t_start_ms"])
    out, last_sync = [], None
    for m in feed:
        p, mid = m["payload"], exp["match_id"]
        if m["kind"] == "status":
            out.append({"type": "match.status", "match_id": mid, "status": p["status"], "period": p["period"],
                        "t_ms": p["t_ms"], "score": p["score"], "sent_at": m["sent_at"]})
        elif m["kind"] == "frame":
            while due and due[0]["t_start_ms"] - 2000 <= p["t_ms"]:
                out.append({"type": "overlay.upsert", "match_id": mid, "overlay": due.pop(0), "sent_at": m["sent_at"]})
            out.append({"type": "frame", "match_id": mid, "frame": p})
            if last_sync is None or p["t_ms"] - last_sync >= 1000:
                last_sync = p["t_ms"]
                out.append({"type": "clock.sync", "match_id": mid, "period": p["period"], "t_ms": p["t_ms"],
                            "speed": 1.0, "server_time": m["sent_at"]})
    return out


def _failed(name: str, messages: list[dict]) -> list[str]:
    return [c.name for c in golden.check(golden.load_case(name), messages).checks if not c.ok]


@pytest.fixture(scope="module")
def goal() -> list[dict]:
    return _stream("showcase-goal")


@pytest.mark.parametrize("name", list(golden.CASES))
def test_a_good_stream_passes(name):
    report = golden.check(golden.load_case(name), _stream(name))
    assert report.passed, report.text()


def test_the_cases_are_up_to_date(tmp_path):
    """Building the cases again gives the committed files, byte for byte."""
    golden.build(data_root=tmp_path / "datasets", truth_root=tmp_path / "truth")
    for name in golden.CASES:
        for built, kept in ((tmp_path / "datasets" / "golden" / name, golden.DATASETS / "golden" / name),
                            (tmp_path / "truth" / "golden" / name, golden.TRUTH / "golden" / name)):
            for f in built.iterdir():
                assert f.read_bytes() == (kept / f.name).read_bytes(), f"{name}/{f.name} is stale; run offball golden build"


def test_the_pipeline_plumbing_passes_without_the_crew(tmp_path):
    """With no crew the pipeline airs nothing, but its frames, clock and score are already right."""
    report = golden.run("showcase-goal", None, tmp_path / "out.jsonl")
    failed = [c.name for c in report.checks if not c.ok]
    assert failed == ["m07-k03 (decoy_run) aired"], report.text()


def _edit(messages: list[dict], fn, kind: str | None = None, mode: str | None = None) -> list[dict]:
    out = copy.deepcopy(messages)
    for m in out:
        o = m.get("overlay")
        if o and (kind is None or o["kind"] == kind) and (mode is None or o["mode"] == mode):
            fn(o)
    return out


def test_a_missing_mode_fails(goal):
    stream = [m for m in goal if not (m["type"] == "overlay.upsert" and m["overlay"]["kind"] == "caption"
                                      and m["overlay"]["mode"] == "audio")]
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) has a caption in every mode"]


def test_a_caption_with_no_english_fails(goal):
    stream = _edit(goal, lambda o: o.update(text={"es": "Hola"}), "caption", "casual")
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) captions are written in English"]


def test_an_arrow_on_the_wrong_path_fails(goal):
    stream = _edit(goal, lambda o: o["anchors"].update(to_xy=[o["anchors"]["to_xy"][0], 60.0]), "run_arrow")
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) run arrow follows kes-09's run"]


def test_a_ring_in_the_wrong_place_fails(goal):
    stream = _edit(goal, lambda o: o["anchors"].update(centre_xy=[o["anchors"]["centre_xy"][0] - 12, 40.0]),
                   "gap_ring")
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) gap ring is on the space that opened"]


def test_a_pass_between_the_wrong_players_fails(goal):
    stream = _edit(goal, lambda o: o["anchors"].update(player_ids=["kes-08", "kes-10"]), "pass_line")
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) pass line joins kes-11 to kes-10"]


def test_a_wrong_pass_length_fails(goal):
    stream = _edit(goal, lambda o: o["data"].update(distance_m=o["data"]["distance_m"] + 5), "pass_line")
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) pass length is 24.1 m"]


def test_a_wrong_number_fails(goal):
    stream = _edit(goal, lambda o: o["data"].update(value=o["data"]["value"] + 4), "stat_card")
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) stat cards match the frames they cite"]


def test_evidence_that_doesnt_exist_or_is_elsewhere_fails(goal):
    for ref in ("m07-e9999", "m07-f2-10000", "m08-f2-27030"):
        stream = _edit(goal, lambda o, r=ref: o.update(evidence_ids=[r]), "caption", "learn")
        assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) every graphic cites evidence from the moment"]


def test_a_flash_fails(goal):
    stream = _edit(goal, lambda o: o.update(t_end_ms=o["t_start_ms"] + 1000), "run_arrow", "casual")
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) graphics hold long enough to read"]


def test_too_many_graphics_at_once_fails(goal):
    stream = _edit(goal, lambda o: o.update(t_start_ms=o["t_start_ms"] - 2000), "gap_ring", "casual")
    assert _failed("showcase-goal", stream) == ["no mode shows more pitch graphics at a time than it allows"]


def test_graphics_sent_late_fail(goal):
    upserts = [m for m in goal if m["type"] == "overlay.upsert"]
    stream = [m for m in goal if m["type"] != "overlay.upsert"] + upserts
    assert _failed("showcase-goal", stream) == ["every graphic arrives in time to be seen"]


def test_unlabelled_graphics_fail(goal):
    stream = _edit(goal, lambda o: o.update(labels=["ai-generated"]), "caption", "player")
    assert _failed("showcase-goal", stream) == ["every graphic is labelled AI-generated on synthetic data"]


def test_held_graphics_dont_count_as_aired(goal):
    stream = _edit(goal, lambda o: o.update(approval="held"))
    assert _failed("showcase-goal", stream) == ["m07-k03 (decoy_run) aired"]


def test_a_broken_contract_fails(goal):
    stream = _edit(goal, lambda o: o.pop("layer"), "caption", "casual")
    assert "every message matches the contracts" in _failed("showcase-goal", stream)


def test_frames_off_the_tracking_fail(goal):
    stream = copy.deepcopy(goal)
    for m in stream:
        if m["type"] == "frame":
            m["frame"]["players"]["kes-09"][0] += 0.5
    assert _failed("showcase-goal", stream) == ["frames carry the tracking as it is"]


def test_a_silent_clock_fails(goal):
    stream = [m for m in goal if not (m["type"] == "clock.sync" and 1_080_000 < m["t_ms"] < 1_085_000)]
    assert _failed("showcase-goal", stream) == ["the clock keeps the feed alive"]


def test_a_wrong_or_early_score_fails(goal):
    wrong = [dict(m, score={"kes": 1, "ash": 1}) if m["type"] == "match.status" else m for m in goal]
    assert "the score is right as the stretch opens" in _failed("showcase-goal", wrong)
    early = [dict(m, t_ms=1_075_000) if m["type"] == "match.status" and m["score"]["kes"] == 1 else m for m in goal]
    assert _failed("showcase-goal", early) == ["the score goes to {'kes': 1, 'ash': 0} as the goal goes in"]


@pytest.mark.parametrize("name", ["showcase-null-run", "null-overlap"])
def test_airing_a_null_moment_fails(name):
    exp = golden.load_case(name)
    mom = exp["moments"][0]
    path = mom["run"]["path"]
    arrow = _overlay(exp, 1, "run_arrow", "casual", mom["t_start_ms"], mom["t_end_ms"] + 2000,
                     {"player_id": mom["creator_id"], "from_xy": path[0][1:], "to_xy": path[-1][1:]},
                     [frame_ref(exp["match_id"], exp["period"], mom["t_start_ms"] // FRAME_MS)], "live-0001")
    failed = _failed(name, _stream(name, [arrow]))
    assert failed == [f"{mom['moment_id']} ({mom['type']}) is not aired as an {mom['parent'].replace('_', ' ')}"
                      if mom["parent"][0] in "aeiou" else
                      f"{mom['moment_id']} ({mom['type']}) is not aired as a {mom['parent'].replace('_', ' ')}"]


def test_the_expectations_follow_the_answer_key():
    exp = golden.load_case("showcase-goal")
    key = json.loads((golden.TRUTH / "showcase" / "m07" / "answer_key.json").read_text(encoding="utf-8"))
    row = next(r for r in key if r["moment_id"] == "m07-k03")
    mom = exp["moments"][0]
    assert (mom["creator_id"], mom["dragged_ids"], mom["receiver_id"]) == ("kes-09", ["ash-05"], "kes-10")
    assert (mom["t_start_ms"], mom["t_end_ms"]) == (row["t_start_ms"], row["t_end_ms"])
    assert exp["score"]["changes"][0]["score"] == {"kes": 1, "ash": 0}
