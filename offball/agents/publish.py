"""Publishing the Producer's schedule as overlay messages (PRD 12.8, 15.2; INTEGRATION.md 4.5).

This step decides nothing. It resolves the beats and anchors the Producer chose into match times and pitch
positions from the moment card, takes the words from the Persona's scripts, and checks the result against the
overlay contract and the house rules (every graphic holds at least 2.5 s). A schedule that breaks them comes
back to the Producer with the reasons.
"""

from __future__ import annotations

import re
from typing import Any

from offball.agents.schemas import LANGS, DraftOut, Localized, ModeScript, PlannedOverlay, Schedule
from offball.contracts import LAYER_OF, Anchors, Overlay, Speech
from offball.core import moment_overlay_id
from offball.services.state import MatchState

MIN_HOLD_MS = 2500
LIVE_BUFFER_MS = 1500


class PublishError(ValueError):
    """The schedule can't be published; the message lists every reason."""


def _beat_times(card: dict, live_clock: tuple[int, int] | None) -> dict[str, int]:
    beats = {b["key"]: b["t_ms"] for b in card["beats"]}
    beats["after"] = card["t_end_ms"] + 1000
    if live_clock:
        beats["now"] = live_clock[1] + LIVE_BUFFER_MS
    return beats


def _player(card: dict, anchor: str) -> str | None:
    if anchor == "runner":
        return card["creator"]["player_id"] if card.get("creator") else None
    if anchor == "defender":
        return card["dragged"][0]["player_id"] if card.get("dragged") else None
    if anchor in ("receiver", "passer"):
        return card[anchor]["player_id"] if card.get(anchor) else None
    return None


def _anchors(card: dict, p: PlannedOverlay) -> tuple[Anchors, dict[str, Any]]:
    """Where a planned graphic sits on the pitch. KeyError names an anchor this moment doesn't have, such as the run of
    a moment that had none, so the Producer hears about it rather than the moment failing."""
    a = card["anchors"]
    if p.anchor in ("runner", "defender", "receiver", "passer"):
        pid = _player(card, p.anchor)
        if pid is None:
            raise KeyError(p.anchor)
        return Anchors(player_id=pid), {}
    if p.anchor == "run":
        r = a["run"]
        if not r.get("from_xy") or not r.get("to_xy"):
            raise KeyError("run")
        return Anchors(player_id=r["player_id"], from_xy=tuple(r["from_xy"]), to_xy=tuple(r["to_xy"])), {"lead_s": 0.8}
    if p.anchor == "defender_move":
        d = a["defender"]
        if not d.get("from_xy"):
            raise KeyError("defender_move")
        return Anchors(player_id=d["player_id"], from_xy=tuple(d["from_xy"])), {"style": "displacement"}
    if p.anchor == "gap":
        g = a["gap"]
        return (Anchors(centre_xy=tuple(g["centre_xy"]), radius_m=max(g["rx_m"], g["ry_m"])),
                {"rx_m": g["rx_m"], "ry_m": g["ry_m"], "with_pass": "pass" in a})
    if p.anchor == "pass":
        pa = a["pass"]
        return Anchors(from_xy=tuple(pa["from_xy"]), to_xy=tuple(pa["to_xy"]), player_ids=pa["player_ids"]), {}
    return Anchors(), {}


def _localized(words: Localized) -> dict[str, str]:
    """A text map for the overlay contract: each language the Persona wrote, leaving out empty ones."""
    return {lang: getattr(words, lang).strip() for lang in LANGS if getattr(words, lang).strip()}


def _speech(oid: str, text: dict[str, str], pan: float | None) -> dict[str, Speech]:
    out = {}
    for lang, words in text.items():
        escaped = words.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        out[lang] = Speech(ssml_ref=f"{oid}.{lang}.ssml", voice="narrator-1",
                           ssml=f'<speak version="1.0" xml:lang="{lang}">{escaped}</speak>', pan=pan)
    return out


def build_overlays(card: dict, scripts: dict[str, ModeScript], schedule: Schedule, draft: DraftOut,
                   live_clock: tuple[int, int] | None) -> list[Overlay]:
    beats = _beat_times(card, live_clock)
    claims = {c.claim_id: c for c in draft.claims}
    beat_evidence = {b["key"]: b["evidence_ids"] for b in card["beats"]}
    period = card["period"]
    pan_gap = max(-1.0, min(1.0, (card["anchors"]["gap"]["centre_xy"][0] - 52.5) / 52.5))
    problems: list[str] = []
    out: list[Overlay] = []
    seen: dict[tuple[str, str], int] = {}
    for k, p in enumerate(schedule.overlays):
        where = f"overlay {k} ({p.mode} {p.kind})"
        script = scripts.get(p.mode)
        if script is None:
            problems.append(f"{where}: there is no {p.mode} script to take words from")
            continue
        missing = [b for b in (p.start_beat, p.end_beat) if b not in beats]
        if missing:
            problems.append(f"{where}: the moment has no beat {missing[0]}")
            continue
        t0 = beats[p.start_beat] + round(p.start_offset_s * 1000)
        t1 = beats[p.end_beat] + round(p.end_offset_s * 1000)
        if t1 - t0 < MIN_HOLD_MS:
            problems.append(f"{where}: it holds {(t1 - t0) / 1000:.1f} s; every graphic holds at least 2.5 s")
            continue
        try:
            anchors, data = _anchors(card, p)
        except KeyError as exc:
            problems.append(f"{where}: the moment card has no anchor {exc}")
            continue
        except ValueError as exc:  # an anchor the card has, but with positions a graphic can't use
            problems.append(f"{where}: the {p.anchor} anchor can't be drawn: {str(exc)[:120]}")
            continue
        text: dict[str, str] = {}
        a11y: dict[str, str] = {}
        claim_ids, line_player = [], None
        if p.text_ref == "line":
            if p.line_index is None or not 0 <= p.line_index < len(script.lines):
                problems.append(f"{where}: line_index {p.line_index} isn't a line of the {p.mode} script")
                continue
            line = script.lines[p.line_index]
            text, a11y = _localized(line.text), _localized(line.a11y_text)
            claim_ids, line_player = line.claim_ids, line.player_id
        elif p.text_ref != "none":
            text = _localized(getattr(script, p.text_ref))
            if not text.get("en"):
                problems.append(f"{where}: the {p.mode} script has no {p.text_ref}")
                continue
        if p.kind == "caption" and not text.get("en"):
            problems.append(f"{where}: a caption needs a line")
            continue
        if p.mode == "player" and p.kind == "caption" and line_player:
            anchors = Anchors(player_id=line_player)
        if p.kind == "stat_card":
            claim = claims.get(script.stat_claim_id or "")
            if claim is None or claim.value is None:
                problems.append(f"{where}: a stat card needs stat_claim_id to point at a verified number claim")
                continue
            data = {"value": claim.value, "unit": claim.unit, "player": f"No. {anchors.player_id.rsplit('-', 1)[1].lstrip('0')}"
                    if anchors.player_id else ""}
            claim_ids = [claim.claim_id]
        if p.kind == "badge":
            data = {"live": "speed", "threshold_kmh": 25.2}
        if not a11y:
            same_beat = [ln for ln in script.lines if ln.beat == p.start_beat]
            a11y = _localized(same_beat[0].a11y_text) if same_beat else dict(text)
        evidence = sorted({e for cid in claim_ids if cid in claims for e in claims[cid].evidence_ids}
                          | set(beat_evidence.get(p.start_beat, [])))
        seen[(p.mode, p.kind)] = seen.get((p.mode, p.kind), 0) + 1
        oid = moment_overlay_id(card["candidate_id"], p.mode, p.kind, seen[(p.mode, p.kind)])
        speak = p.kind == "caption" or (p.mode == "audio" and p.kind == "gap_ring")
        pan = pan_gap if p.mode == "audio" and p.anchor == "gap" else None
        try:
            out.append(Overlay(
                overlay_id=oid, match_id=card["match_id"], period=period, t_start_ms=t0, t_end_ms=t1, kind=p.kind,
                layer=LAYER_OF[p.kind], priority=p.priority, mode=p.mode, anchors=anchors,
                text=text, speech=_speech(oid, text or a11y, pan) if speak else {},
                a11y_text=a11y, data=data or None, evidence_ids=evidence,
                confidence=draft.confidence, approval=p.approval, detected_moment_id=card["candidate_id"]))
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
    if problems:
        raise PublishError("\n".join(problems))
    if not out:
        raise PublishError("the schedule has no graphics")
    return out


def publish_correction(state: MatchState, candidate_id: str, overlays: list[Overlay], event_id: str) -> list[str]:
    """Replace a moment's graphics after a feed correction (INTEGRATION.md 4.3): every replacement goes out first,
    under a new ID with the "correction" label, then each old graphic is retracted, naming the corrected event and
    its replacement. Returns the replacements' IDs."""
    old = [o for o in state.live_overlays() if o.detected_moment_id == candidate_id]
    replaced: dict[str, str] = {}
    for o in overlays:
        k = 1 + sum(oid.startswith(f"{o.overlay_id}-r") for oid in state.overlays)
        new = o.model_copy(update={"overlay_id": f"{o.overlay_id}-r{k}", "rev": 1, "labels": [*o.labels, "correction"]})
        state.upsert_overlay(new)
        replaced[o.overlay_id] = new.overlay_id
    for o in old:
        base = re.sub(r"-r\d+$", "", o.overlay_id)
        state.retract_overlay(o.overlay_id, "correction", corrects_event_id=event_id, replacement_id=replaced.get(base))
    return list(replaced.values())
