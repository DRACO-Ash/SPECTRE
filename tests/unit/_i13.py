"""I13 of the Threat Understanding concept, as one check every template test shares.

Threat and Understanding never share a sentence, no percentage is rendered,
and no band appears without the axis it belongs to before it.
"""

from __future__ import annotations

import re

_BANDS = re.compile(r"\b(MINIMAL|LOW|MEDIUM|HIGH|CRITICAL|MODERATE)\b")
#: The bands each axis admits: Threat on its five-band scale, Understanding on its three.
_ADMITS = {"Threat": {"MINIMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"}, "Understanding": {"LOW", "MODERATE", "HIGH"}}


def i13_problems(sentence: str) -> list[str]:
    """What breaks I13 in one sentence: both axes in it, a percentage, or a band its own axis does not carry.

    Every band must follow an axis label that admits it. An Understanding band
    must follow "Understanding" directly, as "Understanding LOW"; a Threat band
    may come later in a Threat sentence ("could raise the Threat floor to HIGH")
    but must be one of the five Threat bands. LOW and HIGH sit on both scales,
    so in a Threat sentence the words alone cannot say which axis was meant.
    """
    problems = []
    if "Threat" in sentence and "Understanding" in sentence:
        problems.append("both axes share the sentence")
    if "%" in sentence or "per cent" in sentence:
        problems.append("a percentage")
    for match in _BANDS.finditer(sentence):
        before = sentence[:match.start()]
        axes = [axis for axis in _ADMITS if axis in before]
        if not axes:
            problems.append(f"bare {match.group(1)}")
        elif "Understanding" in axes and not before.endswith("Understanding "):
            problems.append(f"{match.group(1)} not directly after Understanding")
        elif match.group(1) not in _ADMITS[axes[0]]:
            problems.append(f"{match.group(1)} is not a {axes[0]} band")
    return problems
