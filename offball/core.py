"""Shared constants and identifiers (PRD 12.8).

Coordinates are metres on a fixed 105 x 68 m pitch: x runs left to right, y bottom to top.
Orientation is in radians, 0 facing positive x, counter-clockwise. Time is milliseconds since the
period's kick-off plus the period number; frame IDs count 25 Hz frames within a period.
"""

from __future__ import annotations

SCHEMA_VERSION = "2.0"
GENERATOR_VERSION = "0.1.0"

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
HALF_LENGTH = PITCH_LENGTH / 2
HALF_WIDTH = PITCH_WIDTH / 2
GOAL_WIDTH = 7.32
GOAL_HEIGHT = 2.44
PENALTY_AREA_DEPTH = 16.5
PENALTY_AREA_WIDTH = 40.32
PENALTY_SPOT = 11.0

HZ = 25
FRAME_MS = 1000 // HZ
DT = FRAME_MS / 1000.0

SPRINT_KMH = 25.2
HSR_KMH = 19.8
SPRINT_MPS = SPRINT_KMH / 3.6
HSR_MPS = HSR_KMH / 3.6


def frame_of(t_ms: int) -> int:
    """Frame index within a period for a time in milliseconds."""
    return t_ms // FRAME_MS


def ms_of(frame_id: int) -> int:
    return frame_id * FRAME_MS


def match_minute(period: int, t_ms: int) -> float:
    """Match minute as a float, counting the second half from 45'."""
    return (period - 1) * 45 + t_ms / 60000.0


def clock_label(period: int, t_ms: int) -> str:
    """Broadcast clock: 63:21, or 45+2:10 in stoppage time."""
    base = (period - 1) * 45
    total_s = t_ms // 1000
    minutes, seconds = divmod(total_s, 60)
    if minutes >= 45:
        extra = minutes - 45
        return f"{base + 45}+{extra}:{seconds:02d}"
    return f"{base + minutes}:{seconds:02d}"


# Identifiers are strings prefixed by the match, so they stay unique across a dataset.


def event_id(match_id: str, n: int) -> str:
    return f"{match_id}-e{n:04d}"


def possession_id(match_id: str, n: int) -> str:
    return f"{match_id}-p{n:04d}"


def frame_ref(match_id: str, period: int, frame_id: int) -> str:
    """Evidence ID for a tracking frame. The period is part of the ID because frame IDs restart each period."""
    return f"{match_id}-f{period}-{frame_id}"


def overlay_id(match_id: str, n: int) -> str:
    return f"{match_id}-o{n:04d}"


def moment_overlay_id(candidate_id: str, mode: str, kind: str, n: int) -> str:
    """A graphic's ID from its moment, mode, kind and place among that mode's graphics of that kind, so a step that
    runs again writes the same IDs (BE-7): `m07-d0220`, casual, caption 2 -> `m07-o0220-casual-caption-2`."""
    match, sep, num = candidate_id.rpartition("-d")
    stem = f"{match}-o{num}" if sep and num.isdigit() else f"{candidate_id}-o"
    return f"{stem}-{mode}-{kind}-{n}"


def counterfactual_id(match_id: str, n: int) -> str:
    return f"{match_id}-c{n:04d}"


def answer_key_id(match_id: str, n: int) -> str:
    return f"{match_id}-k{n:02d}"


def detected_id(match_id: str, n: int) -> str:
    return f"{match_id}-d{n:04d}"


def player_id(club_id: str, number: int) -> str:
    return f"{club_id}-{number:02d}"


def parse_frame_ref(ref: str) -> tuple[str, int, int] | None:
    """`m07-f2-27000` -> ("m07", 2, 27000); None for anything else."""
    head, sep, frame = ref.rpartition("-")
    match, sep2, period = head.rpartition("-f")
    if not (sep and sep2 and match and period.isdigit() and len(period) == 1 and frame.isdigit()):
        return None
    return match, int(period), int(frame)


def parse_event_ref(ref: str) -> tuple[str, int] | None:
    """`m07-e0912` -> ("m07", 912); None for anything else."""
    match, sep, n = ref.rpartition("-e")
    if not (sep and match and n.isdigit() and len(n) >= 4):
        return None
    return match, int(n)


def club_of(pid: str) -> str:
    return pid.split("-", 1)[0]


def number_of(pid: str) -> int:
    return int(pid.rsplit("-", 1)[1])
