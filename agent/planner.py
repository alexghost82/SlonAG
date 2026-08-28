import json
import re
import sys
from pathlib import Path

from i18n import t
from mark.tools.builtin import build_builtin_registry
from mark.tools.registry import ToolRegistry


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


PLANNER_PROMPT = """You are the planning module of Slon, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools in the
canonical catalog appended to these instructions.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- NEVER reference previous step results in parameters. Every step is independent.
- Choose tools and parameters only from the appended canonical catalog.
- Max 5 steps. Use the minimum steps needed.

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def render_planner_tool_catalog(registry: ToolRegistry) -> str:
    """Render planner-visible metadata from the canonical registry."""
    entries = []
    for spec in registry.list():
        schema = json.dumps(
            spec.input_schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        entries.append(
            f"{spec.name}\n"
            f"  description: {spec.description}\n"
            f"  input_schema: {schema}"
        )
    return "AVAILABLE TOOLS (CANONICAL CATALOG):\n\n" + "\n\n".join(entries)


def _system_instruction(registry: ToolRegistry | None) -> str:
    selected_registry = registry if registry is not None else build_builtin_registry()
    catalog = render_planner_tool_catalog(selected_registry)
    return f"{PLANNER_PROMPT.rstrip()}\n\n{catalog}"


def _get_api_key() -> str:
    from config.secrets import get_secret

    key = get_secret("gemini_api_key")
    if key is None:
        raise RuntimeError(t("error.gemini_key_missing"))
    return key


def create_plan(
    goal: str,
    context: str = "",
    *,
    registry: ToolRegistry | None = None,
) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=_system_instruction(registry)
    )

    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        response = model.generate_content(user_input)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = json.loads(text)

        if "steps" not in plan or not isinstance(plan["steps"], list):
            raise ValueError(t("error.invalid_plan_structure"))

        for step in plan["steps"]:
            if step.get("tool") in ("generated_code",):
                print(
                    "[Planner] ⚠️ generated_code detected in step "
                    f"{step.get('step')} — replacing with web_search"
                )
                desc = step.get("description", goal)
                step["tool"] = "web_search"
                step["parameters"] = {"query": desc[:200]}

        print(t("planner.plan_created", n=len(plan["steps"])))
        for s in plan["steps"]:
            print(f"  {t("planner.plan_step", step=s["step"], tool=s["tool"], desc=s['description'])}")

        return plan

    except json.JSONDecodeError as e:
        print(t("planner.plan_json_failed", e=str(e)))
        return _fallback_plan(goal)
    except Exception as e:
        print(t("planner.plan_failed", e=str(e)))
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    print(t("planner.fallback_plan"))
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True
            }
        ]
    }


def replan(
    goal: str,
    completed_steps: list,
    failed_step: dict,
    error: str,
    *,
    registry: ToolRegistry | None = None,
) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=_system_instruction(registry)
    )

    completed_summary = "\n".join(
        f"  - Step {s['step']} ({s['tool']}): DONE" for s in completed_steps
    )

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        response = model.generate_content(prompt)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan     = json.loads(text)

        for step in plan.get("steps", []):
            if step.get("tool") == "generated_code":
                step["tool"] = "web_search"
                step["parameters"] = {"query": step.get("description", goal)[:200]}

        print(t("planner.plan_revised", n=len(plan["steps"])))
        return plan
    except Exception as e:
        print(t("planner.replan_failed", e=str(e)))
        return _fallback_plan(goal)
