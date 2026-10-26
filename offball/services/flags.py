"""Degrade flags (PRD 14.7, 18.14): the only settings the Engineer may change.

Each flag has a normal value. A change is logged with who made it and why, shows in the producer console, and
reverts by itself after 10 minutes unless the producer keeps it; the producer can also undo it at once. Locally the
flags live in memory; in Azure the same interface sits on an App Configuration store that holds nothing else.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

REVERT_AFTER_S = 600

# Each flag, its normal value, and the values a mitigation may set.
FLAGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "explainer.model_tier": ("reasoning", ("reasoning", "fast")),
    "persona.live_languages": ("all", ("all", "en")),
    "producer.density": ("standard", ("standard", "low")),
    "tactician.enabled": ("on", ("on", "off")),
    "voice.enabled": ("on", ("on", "off")),
}


@dataclass
class Change:
    flag: str
    old: str
    new: str
    by: str
    reason: str
    at: float
    revert_at: float | None  # None once the producer keeps it
    state: str = "active"  # active, kept, reverted or undone

    def as_dict(self) -> dict[str, Any]:
        return {"flag": self.flag, "old": self.old, "new": self.new, "by": self.by, "reason": self.reason,
                "at": self.at, "revert_at": self.revert_at, "state": self.state}


@dataclass
class FlagStore:
    values: dict[str, str] = field(default_factory=lambda: {k: v[0] for k, v in FLAGS.items()})
    changes: list[Change] = field(default_factory=list)

    def get(self, flag: str) -> str:
        return self.values[flag]

    def set(self, flag: str, value: str, by: str, reason: str, now: float | None = None) -> Change:
        if flag not in FLAGS:
            raise ValueError(f"No degrade flag {flag}; flags: {', '.join(FLAGS)}")
        if value not in FLAGS[flag][1]:
            raise ValueError(f"{flag} can be {', '.join(FLAGS[flag][1])}, not {value}")
        now = time.time() if now is None else now
        normal = value == FLAGS[flag][0]
        change = Change(flag, self.values[flag], value, by, reason, now, None if normal else now + REVERT_AFTER_S)
        self.values[flag] = value
        self.changes.append(change)
        return change

    def _active(self, flag: str) -> Change | None:
        return next((c for c in reversed(self.changes) if c.flag == flag and c.state in ("active", "kept")), None)

    def keep(self, flag: str) -> Change | None:
        """The producer keeps the latest change, so it won't revert by itself."""
        c = self._active(flag)
        if c:
            c.state, c.revert_at = "kept", None
        return c

    def undo(self, flag: str, by: str = "producer", now: float | None = None) -> Change | None:
        """Put the flag back to its normal value at once."""
        c = self._active(flag)
        if c is None:
            return None
        c.state = "undone"
        return self.set(flag, FLAGS[flag][0], by, f"undid {c.by}'s change", now)

    def expire(self, now: float | None = None) -> list[Change]:
        """Revert every change whose 10 minutes are up. Returns the reverts."""
        now = time.time() if now is None else now
        out = []
        for c in list(self.changes):
            if c.state == "active" and c.revert_at is not None and now >= c.revert_at:
                c.state = "reverted"
                out.append(self.set(c.flag, FLAGS[c.flag][0], "schedule", f"{c.flag} reverted after 10 minutes", now))
        return out

    def snapshot(self) -> dict[str, Any]:
        return {"values": dict(self.values), "normal": {k: v[0] for k, v in FLAGS.items()},
                "changes": [c.as_dict() for c in self.changes[-20:]]}


FLAG_STORE = FlagStore()
