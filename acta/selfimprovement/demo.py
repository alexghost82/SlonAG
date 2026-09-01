"""Demo: run the full self-improvement pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from acta.selfimprovement.collector import MetricsCollector
from acta.selfimprovement.pipeline import SelfImprovementPipeline
from acta.selfimprovement.types import ObservationKind


def main() -> None:
    print("=" * 60)
    print("SlonAG Controlled Self-Improvement — Demo")
    print("=" * 60)

    pipeline = SelfImprovementPipeline()
    collector = MetricsCollector.instance()

    # ── Phase 1: Simulate observations ────────────────────────
    print("\n[Phase 1] Injecting observations...")

    # Simulate tool calls with various outcomes
    for i in range(20):
        collector.record_tool_call("file_read", 120 + i * 10, True, "ok")
    for i in range(8):
        collector.record_tool_call("file_read", 500, True, "ok")
    for i in range(5):
        collector.record_tool_call("web_fetch", 8000, False, "timeout", timeout=True)
    for i in range(3):
        collector.record_tool_call("web_fetch", 3000, False, "network_error")
    for i in range(10):
        collector.record_tool_call("browser_click", 200, True, "ok")

    # Simulate provider calls
    collector.record_provider_call("gemini", 450, True, routing=True)
    collector.record_provider_call("gemini", 380, True, routing=True)
    collector.record_provider_call("openrouter", 1200, True, routing=True)
    collector.record_provider_call("openrouter", 3000, False, routing=True)
    collector.record_provider_call("openrouter", 2500, False, routing=True)
    collector.record_provider_call("local", 150, True, routing=True)
    collector.record_provider_call("local", 200, True, routing=True)
    collector.record_provider_call("openai", 6000, False, timeout=True)
    collector.record_provider_call("openai", 7000, False, timeout=True)

    # Simulate preference corrections
    for i in range(4):
        collector.record_preference_correction(
            "favorite_food",
            "User corrected: prefers 'sushi' not 'pizza'",
            {"old": "pizza", "new": "sushi"},
        )
    collector.record_preference_correction(
        "active_project",
        "User corrected project description",
        {"category": "projects"},
    )

    print("  - 33 tool observations")
    print("  - 8 provider observations")
    print("  - 5 preference corrections")

    # ── Phase 2: Generate candidates ──────────────────────────
    print("\n[Phase 2] Generating improvement candidates...")
    candidates = pipeline.generate_candidates()

    if not candidates:
        print("  No candidates generated (need more observations).")
        print("  Try adding more diverse observations.")
        return

    for i, c in enumerate(candidates, 1):
        risk_tag = f"[{c.risk.value.upper()}]"
        print(f"\n  {i}. {risk_tag} {c.title}")
        print(f"     Category: {c.category.value}")
        print(f"     Evidence: {c.evidence[:100]}...")
        print(f"     Expected: {c.expected_benefit[:80]}...")
        print(f"     Risk:     {c.risk.value}")

    # ── Phase 3: Approve ──────────────────────────────────────
    print("\n[Phase 3] Approving best candidates...")
    for c in candidates[:3]:
        if c.risk in (ObservationKind.SAFE.value if hasattr(ObservationKind, 'SAFE') else "safe",
                       RiskLevel.SAFE, RiskLevel.LOW):
            pipeline.approve(c.id, approved_by="system")
            print(f"  ✓ Approved: {c.title}")

    # ── Phase 4: Apply ────────────────────────────────────────
    print("\n[Phase 4] Applying approved changes...")
    for c in candidates[:3]:
        rec = pipeline._state.improvements.get(c.id)
        if rec and rec.status.value == "approved":
            result = pipeline.apply(c.id)
            if "error" not in result:
                print(f"  ✓ Applied: {c.title}")
            else:
                print(f"  ⚠ Skipped (no persistent change): {c.title}")

    # ── Phase 5: Monitor ──────────────────────────────────────
    print("\n[Phase 5] Monitoring applied improvements...")
    for c in candidates[:2]:
        pipeline.monitor(c.id, benefit_observed="No degradation detected")
        print(f"  ✓ Monitored: {c.title}")

    # ── Phase 6: Rollback (if needed) ─────────────────────────
    print("\n[Phase 6] Simulating rollback for one candidate...")
    if len(candidates) >= 2:
        c = candidates[1]
        pipeline.rollback(c.id, reason="Simulated rollback for demo")
        print(f"  ✓ Rolled back: {c.title}")

    # ── State summary ─────────────────────────────────────────
    print("\n[State] Final state summary:")
    summary = pipeline.get_state_summary()
    for key, value in summary.items():
        if isinstance(value, dict):
            print(f"  {key}:")
            for k, v in value.items():
                print(f"    {k}: {v}")
        else:
            print(f"  {key}: {value}")

    print("\n" + "=" * 60)
    print("Demo complete. State persisted to memory/self_improvement.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
