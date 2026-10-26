"""The Engineer (PRD 14.1, 14.11 `engineer` workflow): watches the crew's health and applies pre-approved mitigations.

Code gathers what the Engineer reads (locally, the crew's own telemetry; in Azure, Azure MCP Server adds Log
Analytics, metrics and the degrade-flag store) and applies what it decides. The Engineer may only change degrade
flags, through the flag store, which logs every change and reverts it after 10 minutes unless the producer keeps it.
Its incident note goes to the match state, so the producer console shows it with an undo.
"""

from __future__ import annotations

import logging
from typing import Any

from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.schemas import EngineerDecision
from offball.contracts import FlagChange, Incident
from offball.services.flags import REVERT_AFTER_S
from offball.services.state import MatchState

log = logging.getLogger("offball.engineer")


def _readings(crew: Crew) -> dict[str, Any]:
    return {"agents": crew.telemetry.summary(), "flags": crew.flags.snapshot()}


async def check(crew: Crew, state: MatchState | None = None, alerts: list[dict] | None = None) -> Incident | None:
    """One look at the system. Returns the incident note when the Engineer changed something or found trouble."""
    crew.flags.expire()
    readings = _readings(crew)
    if not readings["agents"] and not alerts:
        return None  # nothing has run yet: nothing to diagnose
    prompt = f"Telemetry and flags:\n{as_json(readings)}"
    if alerts:
        prompt += f"\n\nAlerts:\n{as_json(alerts)}"
    try:
        d = await crew.ask("engineer", prompt, EngineerDecision, meter=state.tokens if state else None)
    except AgentFailed as exc:
        log.warning("The Engineer couldn't decide: %s", exc)  # alerts still go to the human producer (PRD 14.1)
        return None
    changes: list[FlagChange] = []
    if d.action == "set_flag" and d.flag and d.value:
        current = crew.flags.get(d.flag)
        kept = any(c.flag == d.flag and c.state == "kept" for c in crew.flags.changes)
        if d.value != current and not kept:
            try:
                c = crew.flags.set(d.flag, d.value, by="engineer", reason=d.summary)
            except ValueError as exc:  # outside the playbook's values: nothing changes
                log.warning("The Engineer asked for something the flags don't allow: %s", exc)
            else:
                changes.append(FlagChange(flag=c.flag, old=c.old, new=c.new, revert_after_s=REVERT_AFTER_S))
    if not changes and d.severity == "info":
        return None
    n = 1 + (len(state.of_kind("incident")) if state else 0)
    incident = Incident(incident_id=f"{state.match_id if state else 'ops'}-i{n:03d}", severity=d.severity,
                        summary=d.summary, evidence=d.evidence, changes=changes)
    if state is not None:
        state.append("incident", incident, produced_by="engineer")
    log.info("Incident %s: %s", incident.incident_id, incident.summary)
    return incident
