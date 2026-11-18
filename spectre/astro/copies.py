"""A dataclass instance with some fields changed, typed as the class it was given.

dataclasses.replace builds a new instance of the class it is given, and typeshed types it so. SonarQube's Python
analyser reads its result as the DataclassInstance protocol instead, so every replace returned from a function, or
passed to one, that names the class reads as the wrong type (python:S5886, python:S5655, release 0.48.6). replaced
is dataclasses.replace under a signature that names the class, so both readers see the type it returns.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def replaced[D: DataclassInstance](instance: D, /, **changes: Any) -> D:
    """*instance* with *changes*: dataclasses.replace exactly, the same new instance of the same class."""
    return dataclasses.replace(instance, **changes)
