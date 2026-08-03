"""Deterministic pseudo-randomness for mock adapters.

Mock providers must return the same thing for the same input on every run, or
demos and tests stop being reproducible. Seeding from a hash of the inputs (not
from wall-clock or process state) gives variety across records while keeping
each individual record stable.
"""

from __future__ import annotations

import hashlib
import random


def stable_seed(*parts: object, salt: int = 0) -> int:
    """A stable integer seed derived from the given inputs."""
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return (int(digest[:16], 16) + salt) % (2**63)


def rng_for(*parts: object, salt: int = 0) -> random.Random:
    """A ``random.Random`` seeded stably from the given inputs."""
    return random.Random(stable_seed(*parts, salt=salt))


def pick(items: list, *parts: object, salt: int = 0):
    """Deterministically choose one element of ``items``."""
    return items[stable_seed(*parts, salt=salt) % len(items)]
