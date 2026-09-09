"""Legacy GenerativeModel-shaped wrapper that never imports the SDK here.

Callers that used ``google.generativeai`` should import this module instead.
"""

from __future__ import annotations

from types import SimpleNamespace

from providers.text_ops import LocalOnlyBlocked, complete_text


def configure(api_key: str | None = None, **_kwargs: object) -> None:
    del api_key


class GenerativeModel:
    def __init__(
        self,
        model_name: str = "gemini-2.5-flash",
        system_instruction: str | None = None,
        **_kwargs: object,
    ) -> None:
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, text: object) -> SimpleNamespace:
        prompt = text if isinstance(text, str) else str(text)
        try:
            out = complete_text(
                prompt,
                system=self.system_instruction or "",
                model_id=self.model_name,
            )
        except LocalOnlyBlocked:
            out = ""
        return SimpleNamespace(text=out)
