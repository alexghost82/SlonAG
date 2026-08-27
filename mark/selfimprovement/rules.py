"""Rules engine — generates improvement candidates from observations/metrics."""

from __future__ import annotations

import hashlib
import time
from collections import Counter

from .collector import MetricsCollector
from .types import (
    EvidenceType,
    ImprovementCategory,
    ImprovementCandidate,
    MetricKind,
    ObservationKind,
    RiskLevel,
)


def generate_candidates(
    collector: MetricsCollector | None = None,
    state_count: int = 0,
    max_candidates: int = 10,
) -> list[ImprovementCandidate]:
    """Generate improvement candidates from observed metrics and patterns.

    Returns candidates sorted by risk (SAFE first, HIGH last).
    """
    if collector is None:
        import mark.selfimprovement
        collector = mark.selfimprovement.get_collector()

    candidates: list[ImprovementCandidate] = []

    # Rule 1: High failure rate tools → suggest timeout/retention adjustments
    candidates.extend(_rule_high_failure_tools(collector))

    # Rule 2: Slow tools → suggest timeout increase
    candidates.extend(_rule_slow_tools(collector))

    # Rule 3: Tool timeouts → suggest longer timeout
    candidates.extend(_rule_tool_timeouts(collector))

    # Rule 4: Provider failure patterns → suggest fallback changes
    candidates.extend(_rule_provider_failures(collector))

    # Rule 5: Provider latency imbalance → suggest routing preference changes
    candidates.extend(_rule_provider_latency(collector))

    # Rule 6: Preference corrections → memory extraction refinement
    candidates.extend(_rule_preference_corrections(collector))

    # Rule 7: Config unused detection → suggest cleanup
    candidates.extend(_rule_config_unused(collector))

    # Rule 8: Memory stale/contradiction → memory maintenance
    candidates.extend(_rule_memory_maintenance(collector))

    # Deduplicate by title (fuzzy match)
    candidates = _deduplicate(candidates)

    # Sort by risk (safe first)
    risk_order = {RiskLevel.SAFE: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}
    candidates.sort(key=lambda c: risk_order.get(c.risk, 99))

    return candidates[:max_candidates]


def _rule_high_failure_tools(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """Tools with >30% failure rate get a low-risk review candidate."""
    results = []
    all_stats = collector.all_tool_stats()
    for tool_name, stats in all_stats.items():
        if stats["calls"] < 5:
            continue  # not enough data
        failure_rate = stats["failure_rate"]
        success_rate = stats["success_rate"]
        if failure_rate > 0.30 and failure_rate < 1.0:
            reason = stats["failure_reasons"]
            top_reason = max(reason.items(), key=lambda x: x[1])[0] if reason else "unknown"
            # Check if idempotent → retry is safe
            idempotent_suggestion = "Consider increasing max_tool_calls" if stats.get("timeout_count", 0) > 0 else ""

            candidates_id = _make_id(f"tool-failure-{tool_name}")
            results.append(ImprovementCandidate(
                id=candidates_id,
                category=ImprovementCategory.TOOL_STATS,
                title=f"High failure rate for tool '{tool_name}'",
                description=f"{tool_name} failed {stats['failure_rate']:.0%} of calls ({stats['failure_reasons']}).",
                evidence=f"Statistical evidence from {stats['calls']} calls. Top failure reason: {top_reason}. Success rate: {success_rate:.0%}.",
                evidence_type=EvidenceType.STATISTICAL,
                expected_benefit=f"Reduce failures by identifying root cause and adjusting parameters.",
                risk=RiskLevel.LOW,
                proposed_change={
                    "target": "routing_stats",
                    "action": "flag_tool",
                    "tool": tool_name,
                    "failure_rate": failure_rate,
                },
                rollback_plan="Remove flag from internal state; no persistent change.",
            ))
            break  # one candidate per batch
    return results


def _rule_slow_tools(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """Tools with avg latency >5000ms get timeout increase suggestion."""
    results = []
    all_stats = collector.all_tool_stats()
    for tool_name, stats in all_stats.items():
        if stats["calls"] < 3:
            continue
        avg_ms = stats["avg_latency_ms"]
        if avg_ms > 5000:
            candidates_id = _make_id(f"tool-slow-{tool_name}")
            results.append(ImprovementCandidate(
                id=candidates_id,
                category=ImprovementCategory.WORKFLOW_OPTIMIZATION,
                title=f"Slow tool detected: '{tool_name}' ({avg_ms:.0f}ms avg)",
                description=f"{tool_name} average latency is {avg_ms:.0f}ms across {stats['calls']} calls. This may cause premature timeouts.",
                evidence=f"Statistical: {stats['calls']} calls, {avg_ms:.0f}ms avg, {stats['timeout_count']} timeouts.",
                evidence_type=EvidenceType.STATISTICAL,
                expected_benefit="Avoid timeout failures by adjusting tool timeout settings.",
                risk=RiskLevel.LOW,
                proposed_change={
                    "target": "timeout",
                    "path": f"tool_timeout_{tool_name}",
                    "value": round(avg_ms * 3, 0),  # 3x the observed avg
                    "previous": 30.0,
                },
                rollback_plan="Restore previous timeout value from recorded snapshot.",
            ))
            break
    return results


def _rule_tool_timeouts(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """Tools with frequent timeouts suggest longer timeouts."""
    results = []
    all_stats = collector.all_tool_stats()
    for tool_name, stats in all_stats.items():
        if stats["timeout_count"] >= 3:
            candidates_id = _make_id(f"timeout-{tool_name}")
            results.append(ImprovementCandidate(
                id=candidates_id,
                category=ImprovementCategory.WORKFLOW_OPTIMIZATION,
                title=f"Tool '{tool_name}' timed out {stats['timeout_count']} times",
                description=f"{tool_name} exceeded its timeout {stats['timeout_count']} times in {stats['calls']} calls.",
                evidence=f"Statistical: {stats['timeout_count']} timeouts out of {stats['calls']} total calls.",
                evidence_type=EvidenceType.STATISTICAL,
                expected_benefit="Eliminate timeout failures for this tool.",
                risk=RiskLevel.SAFE,
                proposed_change={
                    "target": "timeout",
                    "path": f"tool_timeout_{tool_name}",
                    "value": 60.0,
                    "previous": 30.0,
                },
                rollback_plan="Restore 30s timeout from snapshot.",
            ))
            break
    return results


def _rule_provider_failures(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """Providers with high failure rate suggest reordering."""
    results = []
    all_stats = collector.all_provider_stats()
    worst = None
    worst_rate = 0.0
    for pid, stats in all_stats.items():
        if stats["calls"] < 5:
            continue
        if stats["failure_rate"] > worst_rate:
            worst_rate = stats["failure_rate"]
            worst = stats
    if worst and worst["calls"] >= 10 and worst["failure_rate"] > 0.2:
        candidates_id = _make_id(f"provider-fail-{worst['provider']}")
        results.append(ImprovementCandidate(
            id=candidates_id,
            category=ImprovementCategory.PROVIDER_PERFORMANCE,
            title=f"Provider '{worst['provider']}' has {worst['failure_rate']:.0%} failure rate",
            description=f"{worst['provider']} failed {worst['failure_rate']:.0%} of calls ({worst['calls']} calls). Consider lowering priority.",
            evidence=f"Statistical: {worst['calls']} calls, {worst['failure_rate']:.0%} failure, {worst.get('avg_latency_ms', 0):.0f}ms avg latency.",
            evidence_type=EvidenceType.STATISTICAL,
            expected_benefit="Improve overall provider reliability by reordering routing preference.",
            risk=RiskLevel.MEDIUM,
            proposed_change={
                "target": "routing_stats",
                "action": "lower_priority",
                "provider": worst["provider"],
                "current_failure_rate": worst["failure_rate"],
            },
            rollback_plan="Revert routing preference order.",
        ))
    return results


def _rule_provider_latency(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """Compare provider latencies and suggest faster alternatives."""
    results = []
    all_stats = collector.all_provider_stats()
    cloud_providers = [pid for pid in all_stats if pid not in {"local", "ollama", "llama_cpp"}]
    if len(cloud_providers) >= 2:
        best = min(
            all_stats.items(),
            key=lambda x: x[1]["avg_latency_ms"],
            default=None,
        )
        slowest = max(
            all_stats.items(),
            key=lambda x: x[1]["avg_latency_ms"],
            default=None,
        )
        if best and slowest and slowest[1]["avg_latency_ms"] > best[1]["avg_latency_ms"] * 2:
            candidates_id = _make_id(f"provider-latency-{slowest[0]}")
            results.append(ImprovementCandidate(
                id=candidates_id,
                category=ImprovementCategory.PROVIDER_PERFORMANCE,
                title=f"Provider '{slowest[0]}' is {slowest[1]['avg_latency_ms']/best[1]['avg_latency_ms']:.1f}x slower than '{best[0]}'",
                description=f"'{slowest[0]}' averages {slowest[1]['avg_latency_ms']:.0f}ms vs '{best[0]}' at {best[1]['avg_latency_ms']:.0f}ms.",
                evidence=f"Statistical: {slowest[1]['calls']} calls on slow, {best[1]['calls']} calls on fast.",
                evidence_type=EvidenceType.STATISTICAL,
                expected_benefit="Reduce response latency by preferring faster providers.",
                risk=RiskLevel.LOW,
                proposed_change={
                    "target": "routing_stats",
                    "action": "prefer_faster_provider",
                    "current": slowest[0],
                    "preferred": best[0],
                    "latency_ratio": slowest[1]["avg_latency_ms"] / best[1]["avg_latency_ms"],
                },
                rollback_plan="Revert routing preference.",
            ))
    return results


def _rule_preference_corrections(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """User corrections to memory/preferences → refine extraction prompts."""
    corrections = collector._preference_corrections[-20:]  # recent ones
    if len(corrections) >= 3:
        types = Counter(c["type"] for c in corrections)
        most_common = types.most_common(1)[0]
        candidates_id = _make_id(f"pref-correction-{most_common[0]}")
        results = [ImprovementCandidate(
            id=candidates_id,
            category=ImprovementCategory.PREFERENCE_REFINEMENT,
            title=f"Multiple corrections for '{most_common[0]}' type ({most_common[1]} corrections)",
            description=f"User corrected {most_common[1]} entries of type '{most_common[0]}'. Memory extraction prompt may need refinement.",
            evidence=f"Pattern evidence: {len(corrections)} corrections in recent session. Most common: {dict(types)}.",
            evidence_type=EvidenceType.PATTERN,
            expected_benefit="Improve memory extraction accuracy by refining LLM extraction prompts.",
            risk=RiskLevel.SAFE,
            proposed_change={
                "target": "memory",
                "action": "refine_extraction_prompt",
                "correction_type": most_common[0],
                "correction_count": len(corrections),
            },
            rollback_plan="Restore original extraction prompt.",
        )]
        return results
    return []


def _rule_config_unused(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """Detect unused configurations."""
    # Simple heuristic: if a provider is never called, suggest disabling
    all_stats = collector.all_provider_stats()
    results = []
    if len(all_stats) >= 3:
        unused = [pid for pid, stats in all_stats.items() if stats["calls"] == 0]
        if unused:
            candidates_id = _make_id(f"config-unused-{unused[0]}")
            results.append(ImprovementCandidate(
                id=candidates_id,
                category=ImprovementCategory.CONFIG_RECOMMENDATION,
                title=f"Provider '{unused[0]}' never used",
                description=f"Provider '{unused[0]}' has never been called. Consider disabling to reduce routing decisions.",
                evidence=f"Pattern: {len(unused)} unused providers out of {len(all_stats)} configured.",
                evidence_type=EvidenceType.PATTERN,
                expected_benefit="Simpler routing decisions, slightly faster selection.",
                risk=RiskLevel.SAFE,
                proposed_change={
                    "target": "routing_stats",
                    "action": "flag_unused_provider",
                    "provider": unused[0],
                },
                rollback_plan="Re-enable provider.",
            ))
    return results


def _rule_memory_maintenance(collector: MetricsCollector) -> list[ImprovementCandidate]:
    """Memory quality improvement candidate."""
    results = []
    observations = collector.recent_observations(
        kind=ObservationKind.MEMORY_STALE, limit=20
    )
    stale_count = len(observations)
    if stale_count >= 2:
        candidates_id = _make_id(f"memory-stale-{stale_count}")
        results.append(ImprovementCandidate(
            id=candidates_id,
            category=ImprovementCategory.MEMORY_QUALITY,
            title=f"Memory stale entries detected ({stale_count} observations)",
            description=f"{stale_count} recent observations suggest stale or outdated memory entries.",
            evidence=f"Pattern evidence: {stale_count} stale observations detected in recent window.",
            evidence_type=EvidenceType.PATTERN,
            expected_benefit="Improved memory relevance and reduced cognitive load from stale entries.",
            risk=RiskLevel.LOW,
            proposed_change={
                "target": "memory",
                "action": "prune_stale_entries",
                "stale_count": stale_count,
            },
            rollback_plan="Restore pruned entries from memory backup.",
        ))
    return results


def _deduplicate(candidates: list[ImprovementCandidate]) -> list[ImprovementCandidate]:
    """Remove near-duplicate candidates (same category + similar title)."""
    seen: set[str] = set()
    unique: list[ImprovementCandidate] = []
    for c in candidates:
        key = f"{c.category.value}:{c.title[:40]}"
        h = hashlib.md5(key.encode()).hexdigest()[:8]
        if h not in seen:
            seen.add(h)
            unique.append(c)
    return unique


def _make_id(prefix: str) -> str:
    """Generate a short unique ID."""
    return f"improve-{prefix}-{int(time.monotonic()) % 100000}"
