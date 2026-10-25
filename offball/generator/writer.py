"""Write a played match to the published formats, and its truth to the held-out store (PRD 12.5-12.9).

Public files (read by ingest, interpret, agents and renderers):
    <data_dir>/match.json, events.jsonl, tracking.parquet, tracking_10hz.parquet
Held-out files (read only by the evaluator and by model training on the training split):
    <truth_dir>/intents.jsonl, probabilities.jsonl, answer_key.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from offball.contracts import Event, Kit, LineupEntry, MatchInfo, PeriodInfo, TeamSheet
from offball.core import FRAME_MS, GENERATOR_VERSION, event_id, possession_id
from offball.generator.engine.sim import MatchResult

INTERNAL_KEYS = ("_serial", "possession_n", "related_serial", "related_player_id")


def match_info(result: MatchResult, engine: str = "emergent", round_: int | None = None) -> MatchInfo:
    sheets = []
    for t in result.teams:
        club = t.club
        on_pitch_ids = set()
        for rec in result.recorders.values():
            used = np.unique(rec.slot_player[: rec.n])
            on_pitch_ids.update(result.players[k].player_id for k in used if k >= 0)
        starters = {p.player_id for p in club.starters()}
        lineup = [
            LineupEntry(player_id=p.player_id, name=p.display, number=p.number, role=p.role, starter=p.player_id in starters)
            for p in club.players
        ]
        sheets.append(
            TeamSheet(club_id=club.club_id, name=club.name, short_name=club.short_name, kit=Kit(**t.kit),
                      formation=t.style.formation, lineup=lineup)
        )
    home, away = result.teams
    periods = []
    for period, n in sorted(result.period_lengths.items()):
        ltr = home.club.club_id if (period == 1) else away.club.club_id
        periods.append(PeriodInfo(period=period, duration_ms=(n - 1) * FRAME_MS, attacks_left_to_right=ltr))
    return MatchInfo(
        match_id=result.match_id,
        seed=result.seed,
        engine=engine,  # type: ignore[arg-type]
        generator_version=GENERATOR_VERSION,
        round=round_,
        home=sheets[0],
        away=sheets[1],
        periods=periods,
        final_score={home.club.club_id: home.score, away.club.club_id: away.score},
    )


def finalise_events(result: MatchResult) -> tuple[list[Event], dict[int, str]]:
    """Order events in time, assign stable IDs, and resolve internal references."""
    raw = sorted(result.events, key=lambda e: (e["period"], e["t_ms"], e["_serial"]))
    serial_to_id = {e["_serial"]: event_id(result.match_id, k + 1) for k, e in enumerate(raw)}
    poss_ids: dict[int, str] = {}
    out = []
    for e in raw:
        n = e.get("possession_n")
        pid = None
        if n is not None and e["type"] not in ("period_start", "period_end"):
            if n not in poss_ids:
                poss_ids[n] = possession_id(result.match_id, len(poss_ids) + 1)
            pid = poss_ids[n]
        related = [serial_to_id[e["related_serial"]]] if e.get("related_serial") in serial_to_id else []
        fields = {k: v for k, v in e.items() if k not in INTERNAL_KEYS}
        fields["event_id"] = serial_to_id[e["_serial"]]
        fields["possession_id"] = pid
        fields["related_event_ids"] = related
        if e["type"] in ("tackle", "foul"):
            fields["opponent_id"] = e.get("related_player_id")
        if e["type"] == "substitution":
            fields["recipient_id"] = e.get("related_player_id")
        out.append(Event.model_validate(fields))
    # Link each pass to the interception that ended it, both ways.
    by_id = {ev.event_id: ev for ev in out}
    for ev in out:
        for rid in ev.related_event_ids:
            other = by_id.get(rid)
            if other is not None and ev.event_id not in other.related_event_ids:
                other.related_event_ids.append(ev.event_id)
    return out, serial_to_id


def tracking_table(result: MatchResult) -> pa.Table:
    """One row per 25 Hz frame: ball x/y/z and x/y/orientation for every player who took part."""
    players = result.players
    used: set[int] = set()
    for rec in result.recorders.values():
        used.update(int(k) for k in np.unique(rec.slot_player[: rec.n]) if k >= 0)
    order = sorted(used)
    columns: dict[str, list[np.ndarray]] = {"period": [], "frame_id": [], "t_ms": [], "ball_x": [], "ball_y": [],
                                            "ball_z": []}
    for k in order:
        pid = players[k].player_id
        for suffix in ("x", "y", "o"):
            columns[f"{pid}_{suffix}"] = []
    for period in sorted(result.recorders):
        rec = result.recorders[period]
        n = result.period_lengths[period]
        frames = np.arange(n)
        columns["period"].append(np.full(n, period, dtype=np.int8))
        columns["frame_id"].append(frames.astype(np.int32))
        columns["t_ms"].append((frames * FRAME_MS).astype(np.int32))
        ball = np.round(rec.ball[:n].astype(np.float64), 2).astype(np.float32)
        columns["ball_x"].append(ball[:, 0])
        columns["ball_y"].append(ball[:, 1])
        columns["ball_z"].append(ball[:, 2])
        sp = rec.slot_player[:n]
        for k in order:
            pid = players[k].player_id
            x = np.full(n, np.nan, dtype=np.float32)
            y = np.full(n, np.nan, dtype=np.float32)
            o = np.full(n, np.nan, dtype=np.float32)
            rows, slots = np.nonzero(sp == k)
            x[rows] = np.round(rec.xy[rows, slots, 0].astype(np.float64), 2)
            y[rows] = np.round(rec.xy[rows, slots, 1].astype(np.float64), 2)
            o[rows] = np.round(rec.ori[rows, slots].astype(np.float64), 3)
            columns[f"{pid}_x"].append(x)
            columns[f"{pid}_y"].append(y)
            columns[f"{pid}_o"].append(o)
    return pa.table({name: np.concatenate(parts) for name, parts in columns.items()})


def downsample_10hz(table: pa.Table) -> pa.Table:
    """The 10 Hz derivative used by calibration checks: positions interpolated at every 100 ms."""
    out_parts = []
    period_col = table.column("period").to_numpy()
    for period in np.unique(period_col):
        sel = np.nonzero(period_col == period)[0]
        sub = table.take(pa.array(sel))
        t = sub.column("t_ms").to_numpy().astype(np.float64)
        t10 = np.arange(0, t[-1] + 1, 100.0)
        cols = {"period": np.full(len(t10), period, dtype=np.int8), "t_ms": t10.astype(np.int32)}
        for name in sub.column_names:
            if name in ("period", "frame_id", "t_ms"):
                continue
            v = sub.column(name).to_numpy(zero_copy_only=False).astype(np.float64)
            cols[name] = np.interp(t10, t, v).astype(np.float32)
            # Keep gaps (players off the pitch) as gaps.
            nan_mask = np.interp(t10, t, np.isnan(v).astype(float)) > 0
            cols[name][nan_mask] = np.nan
        out_parts.append(pa.table(cols))
    return pa.concat_tables(out_parts)


def refresh_manifest(data_dir: Path, truth_dir: Path) -> dict[str, str]:
    """Recompute the hashes of the files a match's manifest lists, after a truth file was rewritten."""
    path = data_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for rel in manifest:
        name = rel.split("/", 1)[1]
        target = data_dir / name if (data_dir / name).exists() else truth_dir / name
        manifest[rel] = file_md5(target)
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_match(
    result: MatchResult,
    data_dir: Path,
    truth_dir: Path,
    engine: str = "emergent",
    round_: int | None = None,
    answer_key: list[dict] | None = None,
) -> dict[str, str]:
    """Write every file for one match. Returns a manifest of file name -> MD5 (for the determinism gate)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    info = match_info(result, engine, round_)
    events, serial_to_id = finalise_events(result)
    # Every text file is written with "\n" line endings, so the same seed gives the same bytes on any OS.
    (data_dir / "match.json").write_text(info.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    with (data_dir / "events.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for ev in events:
            fh.write(ev.model_dump_json(exclude_none=False) + "\n")
    table = tracking_table(result)
    pq.write_table(table, data_dir / "tracking.parquet", compression="zstd", compression_level=9,
                   use_dictionary=False, write_statistics=False)
    pq.write_table(downsample_10hz(table), data_dir / "tracking_10hz.parquet", compression="zstd",
                   compression_level=9, use_dictionary=False, write_statistics=False)

    with (truth_dir / "intents.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for it in result.intents:
            fh.write(json.dumps(it, separators=(",", ":")) + "\n")
    with (truth_dir / "probabilities.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for pr in result.probabilities:
            eid = serial_to_id.get(pr["serial"])
            if eid is None:
                continue
            row = {"event_id": eid, "kind": pr["kind"], "p_success": pr["p_success"], "features": pr["features"]}
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    key = answer_key if answer_key is not None else []
    (truth_dir / "answer_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8", newline="\n")

    manifest = {}
    for path in sorted(list(data_dir.iterdir()) + list(truth_dir.iterdir())):
        if path.is_file() and path.name != "manifest.json":
            manifest[f"{path.parent.name}/{path.name}"] = file_md5(path)
    (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest
