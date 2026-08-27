import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent.runtime import AgentLoop
from i18n import t, AgentLoopResult, LoopBudget
from agent.steering import SteeringQueue
from mark.safety import (
    SafetyDecision,
    SafetyPolicy,
    SafetyPolicyError,
    UnknownToolError,
    UntrustedSource,
)
from mark.tools import ToolExecutor, ToolRegistry, ToolResult
from mark.tools.builtin import build_builtin_registry
from mark.tools.legacy.adapters import with_legacy_speak
from providers.contracts import ModelInfo


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()

class ToolDeniedError(SafetyPolicyError):
    """authorize returned deny, or required confirmation was not granted."""

    def __init__(self, tool_name: str, reason: str = "") -> None:
        self.tool_name = tool_name
        super().__init__(
            "denied",
            reason or "Tool is refused by policy.",
        )


def _get_api_key() -> str:
    """Lazy helper for leftover translate/summarize paths. Not used for tools."""
    from config.secrets import get_secret

    key = get_secret("gemini_api_key")
    if key is None:
        raise RuntimeError(t("error.gemini_key_missing"))
    return key


def _inject_context(
    params: dict, tool: str, step_results: dict, goal: str = ""
) -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                print(t("actions.injecting_translated"))

    return params


def _detect_language(text: str) -> str:
    try:
        import google.generativeai as genai

        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
        response = model.generate_content(
            f"What language is this text written in? "
            "Reply with ONLY the language name in English "
            "(e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        import google.generativeai as genai

        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        target_lang = _detect_language(goal)
        print(t("actions.translating_to", lang=target_lang))

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        response = model.generate_content(prompt)
        translated = response.text.strip()
        print(t("actions.translation_done", lang=target_lang))
        return translated
    except Exception as e:
        print(t("actions.translation_failed", e=str(e)))
        return content


def _registry_with_speak(
    registry: ToolRegistry, speak: Callable | None
) -> ToolRegistry:
    if speak is None:
        return registry
    contextual = ToolRegistry()
    for spec in registry.list():
        contextual.register(
            replace(spec, handler=with_legacy_speak(spec.handler, speak))
        )
    return contextual


def _legacy_result(tool: str, result: ToolResult) -> str:
    """Translate the canonical result only at the legacy agent boundary."""
    if not result.ok:
        denied = result.code == "denied" or result.code.startswith("confirmation")
        if tool == "generated_code" or denied:
            raise ToolDeniedError(tool, result.message)
        if result.code == "unknown_tool":
            raise UnknownToolError(tool)
        raise RuntimeError(t("error.tool_execution_failed", code=str(result.code)))
    if result.message:
        return result.message
    if result.data is None:
        return "Готово."
    if isinstance(result.data, str):
        return result.data
    return str(result.data)


def _call_tool(
    tool: str,
    parameters: dict,
    speak: Callable | None,
    *,
    policy: SafetyPolicy | None = None,
    confirmer: Callable[[SafetyDecision], bool] | None = None,
    source: UntrustedSource | str = UntrustedSource.USER,
    intent: str = "",
    registry: ToolRegistry | None = None,
    tool_executor: ToolExecutor | None = None,
) -> str:
    canonical_registry = registry or build_builtin_registry()
    executor = tool_executor
    if executor is None:
        execution_registry = _registry_with_speak(canonical_registry, speak)
        executor = ToolExecutor(execution_registry, policy or SafetyPolicy(), confirmer)
    result = executor.execute(tool, parameters, source=source, intent=intent)
    return _legacy_result(tool, result)


class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2

    def __init__(
        self,
        policy: SafetyPolicy | None = None,
        confirmer: Callable[[SafetyDecision], bool] | None = None,
        source: UntrustedSource | str = UntrustedSource.USER,
        registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.registry = registry or build_builtin_registry()
        self._policy = policy or SafetyPolicy()
        self._confirmer = confirmer
        self._source = source
        self.tool_executor = tool_executor or ToolExecutor(
            self.registry, self._policy, confirmer
        )

    def _call_tool(
        self, tool: str, parameters: dict, speak: Callable | None, *, intent: str = ""
    ) -> str:
        executor = self.tool_executor
        if speak is not None and executor.__class__ is ToolExecutor:
            executor = ToolExecutor(
                _registry_with_speak(self.registry, speak),
                self._policy,
                self._confirmer,
            )
        return _call_tool(
            tool,
            parameters,
            speak,
            source=self._source,
            intent=intent,
            registry=self.registry,
            tool_executor=executor,
        )

    def execute(
        self,
        goal: str,
        speak: Callable | None = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        from agent.error_handler import ErrorDecision, analyze_error, generate_fix
        from agent.planner import create_plan, replan

        print(f"\n[Executor] {goal}")

        replan_attempts = 0
        completed_steps = []
        step_results = {}
        plan = create_plan(goal)

        while True:
            steps = plan.get("steps", [])

            if not steps:
                msg = "I couldn't create a valid plan for this task, sir."
                if speak:
                    speak(msg)
                return msg

            success = True
            failed_step = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak:
                        speak("Задача отменена.")
                    return "Задача отменена."

                step_num = step.get("step", "?")
                tool = step.get("tool") or ""
                desc = step.get("description", "")
                params = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)

                print(f"\n[Executor] {t("planner.plan_step", step=step_num, tool=tool, desc=desc)}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    try:
                        result = self._call_tool(tool, params, speak, intent=goal)
                        step_results[step_num] = result
                        completed_steps.append(step)
                        print(
                            f"[Executor] ✅ Step {step_num} done: {str(result)[:100]}"
                        )
                        step_ok = True
                        break

                    except Exception as e:
                        error_msg = str(e)
                        print(
                            f"[Executor] ❌ Step {step_num} attempt {attempt} "
                            f"failed: {error_msg}"
                        )

                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")

                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            attempt += 1
                            import time
                            time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Executor] {t("actions.skipping_step", step=step_num)}")
                            completed_steps.append(step)
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Task aborted, sir. {recovery.get('reason', '')}"
                            if speak:
                                speak(msg)
                            return msg

                        else:
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion and tool != "generated_code":
                                try:
                                    fixed_step = generate_fix(
                                        step, error_msg, fix_suggestion
                                    )
                                    if speak:
                                        speak("Пробую альтернативный подход.")
                                    res = self._call_tool(
                                        fixed_step["tool"],
                                        fixed_step["parameters"],
                                        speak,
                                        intent=goal,
                                    )
                                    step_results[step_num] = res
                                    completed_steps.append(step)
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    print(f"[Executor] {t("actions.fix_failed", err=str(fix_err))}")

                            failed_step = step
                            failed_error = error_msg
                            success = False
                            break

                if not step_ok and not failed_step:
                    failed_step = step
                    failed_error = "Max retries exceeded"
                    success = False

                if not success:
                    break

            if success:
                return self._summarize(goal, completed_steps, speak)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Task failed after {replan_attempts} replan attempts, sir."
                if speak:
                    speak(msg)
                return msg

            if speak:
                speak("Корректирую подход.")

            replan_attempts += 1
            plan = replan(goal, completed_steps, failed_step, failed_error)

    def _summarize(
        self, goal: str, completed_steps: list, speak: Callable | None
    ) -> str:
        fallback = (
            f"All done, sir. Completed {len(completed_steps)} steps for: {goal[:60]}."
        )
        try:
            import google.generativeai as genai

            genai.configure(api_key=_get_api_key())
            model = genai.GenerativeModel(model_name="gemini-2.5-flash-lite")
            steps_str = "\n".join(
                f"- {s.get('description', '')}" for s in completed_steps
            )
            prompt = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                "Write a single natural sentence summarizing what was accomplished. "
                "Address the user as 'sir'. Be direct and positive."
            )
            response = model.generate_content(prompt)
            summary = response.text.strip()
            if speak:
                speak(summary)
            return summary
        except Exception:
            if speak:
                speak(fallback)
            return fallback


async def execute_agent_loop(
    user_goal: str,
    *,
    model: ModelInfo,
    provider: Any = None,
    tool_executor: Any = None,
    budget: LoopBudget | None = None,
    steering_queue: SteeringQueue | None = None,
) -> AgentLoopResult:
    """Execute iterative multi-turn AgentLoop engine."""
    loop = AgentLoop(
        provider=provider,
        tool_executor=tool_executor,
        budget=budget,
        model=model,
    )
    return await loop.run(user_goal=user_goal, steering_queue=steering_queue)


def execute_plan(
    goal: str,
    speak: Callable | None = None,
    cancel_flag: threading.Event | None = None,
) -> str:
    """Legacy plan-step execution helper function using AgentExecutor."""
    executor = AgentExecutor()
    return executor.execute(goal, speak=speak, cancel_flag=cancel_flag)
