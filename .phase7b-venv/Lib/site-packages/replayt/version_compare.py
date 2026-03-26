"""Parse replayt-style release versions for simple ordering (major.minor.patch).

Used for optional ``min_replayt_version`` in project config. This is not a full
PEP 440 implementation; it compares the leading numeric X.Y.Z (or shorter) prefix
so typical pins like ``0.4.7`` behave as teams expect.
"""

from __future__ import annotations

# Guard ``int()`` on pathological config strings (min_replayt_version, etc.).
_MAX_NUMERIC_SEGMENT_DIGITS = 20


def replayt_release_tuple(version: str) -> tuple[int, int, int]:
    """Return a three-part tuple for ordering from a version string."""

    s = version.strip()
    if not s:
        msg = "empty version string"
        raise ValueError(msg)

    parts: list[int] = []
    for segment in s.replace("-", ".").split("."):
        seg = segment.lstrip("vV")
        if not seg:
            continue
        num = ""
        for ch in seg:
            if ch.isdigit():
                num += ch
            else:
                break
        if not num:
            if not parts:
                continue
            break
        if len(num) > _MAX_NUMERIC_SEGMENT_DIGITS:
            msg = (
                f"version numeric segment longer than {_MAX_NUMERIC_SEGMENT_DIGITS} digits in {version!r}"
            )
            raise ValueError(msg)
        parts.append(int(num))
        if len(parts) >= 3:
            break

    if not parts:
        msg = f"no numeric version segments in {version!r}"
        raise ValueError(msg)

    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])
