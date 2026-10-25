"""Oracle labels for moments nobody planted (PRD 12.4 step 9, 12.7).

When the emergent engine's own players decide to make a run the moment library knows (a decoy run, an overlap,
a run in behind), the decision log names who and when. The oracle takes those participants and confirms the
moment with the same signal definitions the detectors use: an oracle detector given the participants (gate 6).
Oracle rows carry no counterfactual, because there is no checkpoint at a moment nobody planted.
"""

from __future__ import annotations

from offball.contracts import AnswerKeyMoment
from offball.core import answer_key_id
from offball.models.candidates import detect
from offball.models.match_data import MatchData

# The engine's own decisions and the moment each one can become.
ORACLE_INTENTS = {"decoy_run": "decoy_run", "overlap": "overlap", "run": "timed_run_in_behind"}


def oracle_labels(md: MatchData, intents: list[dict], first_n: int = 1) -> list[AnswerKeyMoment]:
    from offball.generator.director import EXPECTED

    cands = [c for c in detect(md) if c.status == "confirmed"]
    used: set[str] = set()
    rows: list[AnswerKeyMoment] = []
    for it in intents:
        kind = ORACLE_INTENTS.get(it.get("intent", ""))
        if kind is None:
            continue
        near = [c for c in cands if c.type == kind and c.creator_id == it["player_id"] and c.period == it["period"]
                and abs(c.t_start_ms - it["t_ms"]) <= 3000 and c.candidate_id not in used]
        if not near:
            continue
        c = min(near, key=lambda c: abs(c.t_start_ms - it["t_ms"]))
        used.add(c.candidate_id)
        rows.append(AnswerKeyMoment(
            moment_id=answer_key_id(md.match_id, first_n + len(rows)), match_id=md.match_id, source="oracle", type=kind,
            period=c.period, t_start_ms=c.t_start_ms, t_end_ms=c.t_end_ms, team_id=c.team_id, creator_id=c.creator_id,
            dragged_ids=c.dragged_ids, receiver_id=c.receiver_id, gap_zone=c.gap_zone, expected=EXPECTED.get(kind, {}),
            observed={s.name: s.value for s in c.signals}, counterfactual=None, is_null=False, outcome=None, attempts=0,
        ))
    return rows
