"""Compose the spoken 'where is the bus' sentence (pure logic)."""

from __future__ import annotations

import re
from datetime import datetime

from .calibration import TripRecord, checkpoint_stats
from .geo import compass
from .models import Alert, Checkpoint
from .streets import MAX_ON_STREET_M, StreetInfo

_SUFFIXES = {
    "st": "Street", "ave": "Avenue", "av": "Avenue", "rd": "Road", "dr": "Drive",
    "blvd": "Boulevard", "ln": "Lane", "ct": "Court", "cir": "Circle", "pl": "Place",
    "pkwy": "Parkway", "hwy": "Highway", "ter": "Terrace", "trl": "Trail", "sq": "Square",
}  # fmt: skip
_DIRECTIONS = {"n": "North", "s": "South", "e": "East", "w": "West",
               "ne": "Northeast", "nw": "Northwest", "se": "Southeast", "sw": "Southwest"}  # fmt: skip


def speakable(name: str) -> str:
    """Expand abbreviations a text-to-speech voice would mangle ('N Oak Ave' -> 'North Oak Avenue')."""
    words = name.split()
    out = []
    for i, word in enumerate(words):
        key = re.sub(r"\.$", "", word).lower()
        if i == len(words) - 1 and len(words) > 1 and key in _SUFFIXES:
            out.append(_SUFFIXES[key])
        elif i < len(words) - 1 and key in _DIRECTIONS:
            out.append(_DIRECTIONS[key])
        else:
            out.append(word)
    return " ".join(out)


def estimate_eta_min(
    crossings: dict[str, datetime],
    checkpoints: tuple[Checkpoint, ...],
    trips: list[TripRecord],
    now: datetime,
) -> int | None:
    """Minutes to the stop based on the last checkpoint passed.

    Prefers the measured baseline for that checkpoint; falls back to its nominal minutes.
    """
    passed = [(t, c) for c in checkpoints if (t := crossings.get(c.label)) is not None]
    if not passed:
        return None
    crossed_at, cp = max(passed, key=lambda item: item[0])
    stats = checkpoint_stats(trips, cp.label)
    total = stats["median"] if stats else (cp.minutes or None)
    if total is None:
        return None
    elapsed = (now - crossed_at).total_seconds() / 60
    return max(1, round(total - elapsed))


def _distance_text(metres: float, imperial: bool) -> str:
    if imperial:
        feet = metres * 3.28084
        if feet < 1000:
            return f"{round(feet, -1):.0f} feet"
        miles = metres / 1609.344
        return f"{miles:.1f} miles"
    if metres < 1000:
        return f"{round(metres, -1):.0f} meters"
    return f"{metres / 1000:.1f} kilometers"


def _where(info: StreetInfo | None) -> str | None:
    if info is None or info.street is None:
        return None
    street = speakable(info.street)
    ahead = speakable(info.ahead) if info.ahead else None
    behind = speakable(info.behind) if info.behind else None
    if info.distance_m is not None and info.distance_m > MAX_ON_STREET_M:
        return f"near {street}"
    if ahead and behind and ahead != behind:
        return f"on {street} between {behind} and {ahead}"
    if ahead or behind:
        return f"on {street} near {ahead or behind}"
    return f"on {street}"


def compose(
    *,
    bus_name: str,
    info: StreetInfo | None,
    heading: float | None,
    speed_mps: float,
    age_s: float,
    distance_to_stop_m: float | None,
    eta_min: int | None,
    arrived: bool,
    imperial: bool = True,
) -> str:
    """One natural sentence for a smart speaker."""
    if arrived:
        return f"{bus_name} has arrived at your stop."
    parts: list[str] = []
    prefix = ""
    if age_s > 600:
        prefix = f"{bus_name} last reported {round(age_s / 60)} minutes ago. "
    where = _where(info)
    parts.append(f"{bus_name} was" if prefix else f"{bus_name} is")
    parts[0] += f" {where}" if where else " somewhere I couldn't name a street for"
    if speed_mps < 1.0:
        parts.append("currently stopped")
    elif heading is not None:
        parts.append(f"heading {compass(heading)}")
    if distance_to_stop_m is not None:
        parts.append(f"about {_distance_text(distance_to_stop_m, imperial)} from your stop")
    sentence = ", ".join(parts)
    if eta_min is not None:
        sentence += f", roughly {eta_min} minute{'s' if eta_min != 1 else ''} away"
    return f"{prefix}{sentence}."


def alert_message(alert: Alert) -> str:
    """The sentence to speak for an alert (sent as the event's `message`)."""
    bus = alert.bus_name
    if alert.kind == "checkpoint":
        if alert.extra.get("type") == "street":
            return f"{bus} is at {speakable(alert.extra.get('street') or alert.label)}."
        if alert.minutes:
            return f"{bus} is about {alert.minutes} minute{'s' if alert.minutes != 1 else ''} away."
        return f"{bus} is getting close ({alert.label})."
    if alert.kind == "arrived":
        return f"{bus} has arrived."
    if alert.kind == "late":
        late = alert.extra.get("minutes_late")
        if late:
            return f"{bus} is running about {late} minute{'s' if late != 1 else ''} late."
        return f"{bus} is running late."
    if alert.kind == "offline":
        return f"{bus} has stopped reporting its location."
    return f"{bus}: {alert.label}."
