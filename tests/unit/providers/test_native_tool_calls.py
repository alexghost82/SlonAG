from types import SimpleNamespace

from providers.gemini.provider import _tool_calls_of
from providers.openai.provider import _tool_calls as openai_tool_calls
from providers.openrouter.provider import _tool_calls as openrouter_tool_calls


def test_gemini_native_function_call_keeps_correlation() -> None:
    call = SimpleNamespace(id="g-1", name="read_file", args={"path": "a.txt"})
    parsed = _tool_calls_of(SimpleNamespace(function_calls=[call]))
    assert parsed[0].id == "g-1"
    assert parsed[0].arguments == {"path": "a.txt"}


def test_openai_malformed_arguments_remain_observable() -> None:
    parsed = openai_tool_calls({"choices": [{"message": {"tool_calls": [
        {"id": "o-1", "function": {"name": "read_file", "arguments": "{"}}
    ]}}]})
    assert parsed[0].id == "o-1"
    assert "_malformed_arguments" in parsed[0].arguments


def test_openrouter_native_tool_call_keeps_correlation() -> None:
    parsed = openrouter_tool_calls({"choices": [{"message": {"tool_calls": [
        {"id": "or-1", "function": {"name": "weather_report", "arguments": '{"city":"Haifa"}'}},
    ]}}]})
    assert parsed[0].id == "or-1"
    assert parsed[0].arguments == {"city": "Haifa"}
