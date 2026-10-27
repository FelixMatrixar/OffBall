"""The Tactician (PRD 10.10, 14.1): puts a what-if replay's result into words, in English, Spanish and French.

The counterfactual workers measure what a player's decision caused; the Tactician says it. Every number it writes
must be one it was given, with the same value: a draft that cites a number it wasn't given, or misquotes one, goes
back once with the problem. If it is still wrong, the what-if shows its numbers without words, as a step whose agent
fails says nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from offball.agents.crew import AgentFailed, Crew, as_json
from offball.agents.schemas import LANGS, TacticianOut
from offball.mcp import tools as T

log = logging.getLogger("offball.tactician")

# What the player did in the replays, for the prompt.
ALTERNATIVE_WORDS = {
    "hold": "held his place in the team's shape instead",
    "inside": "came inside off the touchline instead",
    "drop": "dropped towards the ball instead",
}


def misquoted(out: TacticianOut, numbers: dict[str, float]) -> list[str]:
    """Numbers the Tactician wrote that it wasn't given, or gave a different value. The sign may go: a negative
    space created is rightly said as that much less."""
    problems = []
    for n in out.numbers:
        if n.name not in numbers:
            problems.append(f"{n.name} is not one of the numbers given")
        elif abs(abs(n.value) - abs(numbers[n.name])) > 0.05 + 0.01 * abs(numbers[n.name]):
            problems.append(f"{n.name} is {numbers[n.name]}, not {n.value}")
    return problems


async def explain(crew: Crew, card: dict[str, Any], option: str, numbers: dict[str, float]) -> TacticianOut | None:
    """The what-if in words, or None when the Tactician can't give a faithful answer."""
    glossary = {lang: T.glossary(lang).get(card["type"], "") for lang in LANGS}
    base = (f"Moment card:\n{as_json(card)}\n\nIn the replays the player {ALTERNATIVE_WORDS[option]}.\n\n"
            f"Numbers from the replays:\n{as_json(numbers)}\n\nThe moment type in each language's glossary:\n"
            f"{as_json(glossary)}")
    prompt = base
    for _ in (1, 2):
        try:
            out = await crew.ask("tactician", prompt, TacticianOut)
        except AgentFailed:
            return None
        problems = misquoted(out, numbers)
        if not problems:
            return out
        log.warning("The Tactician misquoted %s: %s", card["candidate_id"], "; ".join(problems))
        prompt = f"{base}\n\nYour previous answer misquoted numbers:\n" + "\n".join(problems) + "\nWrite it again."
    return None
