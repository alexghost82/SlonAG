"""Controlled preference learning for Slon Agent.

Stores explicit preferences, repeated choices, corrections, habits,
and interaction tendencies with full provenance, confidence tracking,
and decision influence hooks.
"""

from __future__ import annotations

from acta.preference_learning.engine import (
    PreferenceEngine,
)
from acta.preference_learning.repository import (
    PreferenceRepository,
)
from acta.preference_learning.types import (
    ConfidenceDecayPolicy,
    LearnedItem,
    LearningSource,
    PreferenceAction,
    PreferenceType,
    PreferenceVersion,
    PriorityLevel,
    RetrievalContext,
)

__all__ = [
    "ConfidenceDecayPolicy",
    "LearningSource",
    "LearnedItem",
    "PreferenceAction",
    "PreferenceType",
    "PreferenceEngine",
    "PreferenceRepository",
    "PriorityLevel",
    "PreferenceVersion",
    "RetrievalContext",
]
