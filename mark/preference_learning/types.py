"""Data models for the controlled preference learning system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from uuid import uuid4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PreferenceType(str, Enum):
    """Kinds of learnable preference."""
    EXPLICIT = "explicit"          # Directly stated by user
    CHOICE = "choice"              # Repeatedly chosen
    HABIT = "habit"                # Recurring pattern
    CORRECTION = "correction"      # User said "no, do X instead"
    INTERACTION = "interaction"    # Interaction tendency (e.g. prefers concise)
    PROJECT_CONTEXT = "project"    # Project-specific preference


class LearningSource(str, Enum):
    """Where the learning originated."""
    USER_STATED = "user_stated"
    AGENT_OBSERVED = "agent_observed"
    PATTERN_DETECTED = "pattern_detected"
    CORRECTION_RECEIVED = "correction_received"
    MANUAL_ENTRY = "manual_entry"
    SYSTEM_DEDUCED = "system_deduced"


class PreferenceAction(str, Enum):
    """What the Agent should do when this preference is relevant."""
    APPLY = "apply"                # Use this preference to make decisions
    AVOID = "avoid"                # Avoid this option
    PROMPT = "prompt"              # Ask user before deciding
    INFORM = "inform"              # Just consider, don't enforce
    OVERRIDE = "override"          # Overrides lower-priority preferences


class PriorityLevel(str, Enum):
    """How strongly to enforce when relevant."""
    CRITICAL = "critical"          # Non-negotiable
    HIGH = "high"                  # Strong preference
    MEDIUM = "medium"              # Default preference
    LOW = "low"                    # Nice to have


class ConfidenceDecayPolicy(str, Enum):
    """How confidence degrades over time without reinforcement."""
    NONE = "none"                  # No decay (explicit preferences)
    LINEAR = "linear"              # -0.05 per day
    EXPONENTIAL = "exponential"    # *0.95 per week


# ---------------------------------------------------------------------------
# Core data classes
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """Provenance for a learned preference."""
    text: str                     # What the user/context said
    context: str = ""             # Where it happened (tool, turn, session)
    timestamp: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict:
        return {"text": self.text, "context": self.context, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, d: dict) -> Evidence:
        return cls(
            text=d.get("text", ""),
            context=d.get("context", ""),
            timestamp=d.get("timestamp", _now()),
        )


@dataclass
class PreferenceVersion:
    """A single version of a preference with its state."""
    id: str = field(default_factory=lambda: uuid4().hex)
    version: int = 1
    type: PreferenceType = PreferenceType.EXPLICIT
    action: PreferenceAction = PreferenceAction.APPLY
    priority: PriorityLevel = PriorityLevel.MEDIUM
    category: str = ""              # e.g. "ui", "communication", "automation"
    key: str = ""                   # Short identifier
    value: str = ""                 # The preference value
    description: str = ""           # Human-readable description
    confidence: float = 1.0         # 0.0-1.0
    decay_policy: ConfidenceDecayPolicy = ConfidenceDecayPolicy.NONE
    max_reinforcements: int = 50
    reinforcement_count: int = 0
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    last_use_at: str = ""
    usage_count: int = 0

    # Contradiction / correction tracking
    contradicted: bool = False
    contradiction_evidence: list[dict] = field(default_factory=list)
    corrected: bool = False
    correction_source: LearningSource = LearningSource.MANUAL_ENTRY
    correction_reason: str = ""
    deleted: bool = False

    # Tags for filtering
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "type": self.type.value,
            "action": self.action.value,
            "priority": self.priority.value,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "description": self.description,
            "confidence": self.confidence,
            "decay_policy": self.decay_policy.value,
            "max_reinforcements": self.max_reinforcements,
            "reinforcement_count": self.reinforcement_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_use_at": self.last_use_at,
            "usage_count": self.usage_count,
            "contradicted": self.contradicted,
            "contradiction_evidence": self.contradiction_evidence,
            "corrected": self.corrected,
            "correction_source": self.correction_source.value,
            "correction_reason": self.correction_reason,
            "deleted": self.deleted,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PreferenceVersion:
        return cls(
            id=d.get("id", ""),
            version=d.get("version", 1),
            type=PreferenceType(d.get("type", "explicit")),
            action=PreferenceAction(d.get("action", "apply")),
            priority=PriorityLevel(d.get("priority", "medium")),
            category=d.get("category", ""),
            key=d.get("key", ""),
            value=d.get("value", ""),
            description=d.get("description", ""),
            confidence=d.get("confidence", 1.0),
            decay_policy=ConfidenceDecayPolicy(d.get("decay_policy", "none")),
            max_reinforcements=d.get("max_reinforcements", 50),
            reinforcement_count=d.get("reinforcement_count", 0),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
            last_use_at=d.get("last_use_at", ""),
            usage_count=d.get("usage_count", 0),
            contradicted=d.get("contradicted", False),
            contradiction_evidence=d.get("contradiction_evidence", []),
            corrected=d.get("corrected", False),
            correction_source=LearningSource(d.get("correction_source", "manual_entry")),
            correction_reason=d.get("correction_reason", ""),
            deleted=d.get("deleted", False),
            tags=d.get("tags", []),
        )


@dataclass
class LearnedItem:
    """A complete preference record with history."""
    id: str = field(default_factory=lambda: uuid4().hex)
    versions: list[PreferenceVersion] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _now())

    @property
    def active(self) -> PreferenceVersion | None:
        """Return the latest non-deleted version, or the latest version."""
        versions = sorted(self.versions, key=lambda v: v.version, reverse=True)
        for v in versions:
            if not v.deleted:
                return v
        return versions[0] if versions else None

    @property
    def key(self) -> str:
        active = self.active
        return active.key if active else ""

    @property
    def value(self) -> str:
        active = self.active
        return active.value if active else ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "versions": [v.to_dict() for v in self.versions],
            "created_at": self.created_at,
            "active_version": self.versions[-1].version if self.versions else 0,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LearnedItem:
        return cls(
            id=d.get("id", ""),
            versions=[PreferenceVersion.from_dict(v) for v in d.get("versions", [])],
            created_at=d.get("created_at", _now()),
        )


# ---------------------------------------------------------------------------
# Query / context
# ---------------------------------------------------------------------------

@dataclass
class RetrievalContext:
    """Context that the engine uses to filter matching preferences."""
    current_task: str = ""
    tool_name: str = ""
    category_filter: str = ""
    min_confidence: float = 0.3
    max_results: int = 5


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Secret filtering patterns
# ---------------------------------------------------------------------------

# Keys that should never be exported in plain text
SENSITIVE_KEY_PATTERNS = (
    "password", "passwd", "pwd",
    "token", "api_key", "apikey", "api-key", "api_secret", "apisecret",
    "secret", "credential", "auth", "private_key", "privatekey",
    "access_key", "accesskey", "bearer", "cookie", "session",
    "ssh_key", "sshkey", "gpg_key", "pgp",
    "connection_string", "dsn", "database_url",
    "stripe", "aws_access", "gcp_service", "azure",
    "master_key", "root_key", "encryption_key",
)


def _is_sensitive_key(key: str) -> bool:
    """Return True if the key looks like it stores a secret."""
    lower = key.lower()
    return any(pattern in lower for pattern in SENSITIVE_KEY_PATTERNS)


def mask_value(value: str) -> str:
    """Return a masked version of a sensitive value."""
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]
