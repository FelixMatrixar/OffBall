"""Event-driven re-entry (PRD 14.2, 14.11): a feed correction sends what is on air back to the Fact-checker.

Ingest appends a `correction` envelope when the feed corrects an event. Code finds the graphics on air that cite
that event and the verified draft behind each moment; the Fact-checker re-checks the draft against the corrected
data. A draft that still holds stays on air. One that doesn't goes back through the crew from the Explainer, and
its new graphics replace the old ones with a Correction tag. If the Fact-checker can't answer, the moment's
graphics come off air, because nothing unverified airs (PRD 14.1).
"""

from __future__ import annotations

import logging

from offball.agents.broadcast import Outcome, run_moment
from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.schemas import VerdictOut
from offball.services.state import MatchState

log = logging.getLogger("offball.corrections")


def _aired_draft(state: MatchState, candidate_id: str) -> dict | None:
    """The draft the Fact-checker last passed for a moment."""
    passed = [e.payload["draft_id"] for e in state.of_kind("verdict")
              if e.payload.get("candidate_id") == candidate_id and e.payload.get("passed")]
    if not passed:
        return None
    return next((e.payload for e in reversed(state.of_kind("draft")) if e.payload.get("draft_id") == passed[-1]), None)


async def handle_correction(crew: Crew, state: MatchState, match_id: str, event_id: str,
                            settings: dict | None = None) -> list[Outcome]:
    """Re-check every moment on air that cites `event_id`, and replace or retract what no longer holds."""
    cited = [o.detected_moment_id for o in state.live_overlays()
             if event_id in o.evidence_ids and o.detected_moment_id]
    outcomes = []
    for cid in dict.fromkeys(cited):
        draft = _aired_draft(state, cid)
        prompt = (f"A feed correction changed event {event_id} in match {match_id}; get_evidence returns the corrected "
                  f"event. Re-check this aired draft against the corrected data.\n\nDraft:\n{as_json(draft)}")
        try:
            v = await crew.ask("factchecker", prompt, VerdictOut, meter=state.tokens)
        except AgentFailed as exc:
            for o in [o for o in state.live_overlays() if o.detected_moment_id == cid]:
                state.retract_overlay(o.overlay_id, "correction", corrects_event_id=event_id)
            outcome = Outcome(cid, "retracted", [], f"the re-check failed, so the moment came off air: {exc}")
        else:
            holds = draft is not None and v.passed and all(c.ok for c in v.checks)
            state.append("recheck", {"candidate_id": cid, "event_id": event_id, "passed": holds,
                                     "checks": [c.model_dump(mode="json") for c in v.checks]}, produced_by="factchecker")
            if holds:
                outcome = Outcome(cid, "kept", [], f"the aired claims still hold after the correction to {event_id}")
            else:
                fix = {"event_id": event_id, "verdict": v.model_dump(mode="json")}
                outcome = await run_moment(crew, state, match_id, cid,
                                           {"min_gap_s": 20, "approval": "auto", **(settings or {}), "correction": fix})
                if outcome.status != "corrected":
                    # The crew couldn't produce a verified replacement: take the old graphics off air.
                    for o in [o for o in state.live_overlays() if o.detected_moment_id == cid]:
                        state.retract_overlay(o.overlay_id, "correction", corrects_event_id=event_id)
                    outcome = Outcome(cid, "retracted", [], f"no verified replacement: {outcome.note}")
        if outcome.status != "corrected":  # run_moment already logged a correction it published
            state.append("outcome", {"candidate_id": cid, "status": outcome.status,
                                     "overlay_ids": outcome.overlay_ids, "note": outcome.note}, produced_by="corrections")
        log.info("Correction to %s, %s: %s %s", event_id, cid, outcome.status, outcome.note)
        outcomes.append(outcome)
    return outcomes
