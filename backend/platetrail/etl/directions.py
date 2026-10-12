"""Parse OSM camera direction tags into compass bearings.

OSM values seen for `camera:direction` / `direction` include plain degrees
("90"), multiple directions ("90;270"), compass points ("NE", "NNW"), and
ranges ("45-135", taken as the midpoint). Relative values like "forward" or
"backward" depend on the way a node sits on, which a standalone camera node
doesn't have, so they are treated as unparseable rather than guessed.
"""

import re

# Tags checked in priority order. `direction` comes first because it is the
# convention in this data (55 of 56 cameras carry only `direction`; DeFlock
# writes it). Both keys are documented as the way the camera faces.
DIRECTION_TAGS = ("direction", "camera:direction", "surveillance:direction")

_COMPASS = {
    name: i * 22.5
    for i, name in enumerate(
        ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    )
}
_NUMBER = r"-?\d+(?:\.\d+)?"
_RANGE = re.compile(rf"^({_NUMBER})\s*-\s*({_NUMBER})$")


def normalize_bearing(deg: float) -> float:
    return deg % 360.0


def _parse_part(part: str) -> float | None:
    part = part.strip().upper()
    if not part:
        return None
    if part in _COMPASS:
        return _COMPASS[part]
    if re.fullmatch(_NUMBER, part):
        return normalize_bearing(float(part))
    m = _RANGE.match(part)
    if m:
        start, end = (normalize_bearing(float(x)) for x in m.groups())
        span = (end - start) % 360.0  # clockwise from start to end
        return normalize_bearing(start + span / 2.0)
    return None


def parse_direction(value: str | None) -> list[float] | None:
    """Return bearings in [0, 360) for a tag value, or None if absent/unparseable.

    A value is only accepted if every ';'-separated part parses, so a partly
    garbled tag is reported rather than half-used.
    """
    if value is None or not value.strip():
        return None
    parsed = [_parse_part(p) for p in value.split(";")]
    if not parsed or any(b is None for b in parsed):
        return None
    out: list[float] = []
    for b in parsed:
        if b not in out:
            out.append(b)
    return out


def direction_from_tags(tags: dict[str, str]) -> tuple[list[float] | None, str | None, str | None]:
    """(bearings, raw value, tag key) from the first direction tag present."""
    for key in DIRECTION_TAGS:
        if key in tags:
            return parse_direction(tags[key]), tags[key], key
    return None, None, None


def conflicting_direction_tags(tags: dict[str, str], tol_deg: float = 30.0) -> dict[str, str] | None:
    """Direction tags whose parsed bearings disagree with each other, else None.

    The first tag in DIRECTION_TAGS still wins when loading; this only flags
    the disagreement so it can be reported instead of silently resolved.
    """
    present = {k: tags[k] for k in DIRECTION_TAGS if k in tags}
    parsed = {k: parse_direction(v) for k, v in present.items()}
    usable = [b for b in parsed.values() if b]
    if len(usable) < 2:
        return None
    first = usable[0]
    for other in usable[1:]:
        for b in other:
            if all(min(abs(b - a) % 360, 360 - abs(b - a) % 360) > tol_deg for a in first):
                return present
    return None
