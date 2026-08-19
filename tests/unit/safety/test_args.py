"""Argument schema checks. Error text must not echo secrets."""

from __future__ import annotations

import pytest

from mark.safety import (
    CODE_INVALID_ARGS,
    ArgValidationError,
    authorize,
    validate_args,
)

SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"
GEMINI_LIKE = "AIzaSyDummyValueThatLooksLikeAKey99"


def test_valid_file_controller_args_are_returned() -> None:
    checked = validate_args(
        "file_controller",
        {"action": "write", "path": "desktop", "content": "hello"},
    )
    assert checked["action"] == "write"
    assert checked["content"] == "hello"


def test_bad_args_raise_arg_validation_error() -> None:
    with pytest.raises(ArgValidationError) as missing:
        validate_args("file_controller", {})
    assert missing.value.code == CODE_INVALID_ARGS
    assert missing.value.field == "action"

    with pytest.raises(ArgValidationError) as wrong_type:
        validate_args("file_controller", {"action": 2})
    assert wrong_type.value.code == CODE_INVALID_ARGS
    assert wrong_type.value.field == "action"

    with pytest.raises(ArgValidationError):
        validate_args("generated_code", {"description": ["not", "text"]})

    with pytest.raises(ArgValidationError):
        validate_args("file_controller", ["action"])


def test_authorize_rejects_non_mapping_args() -> None:
    with pytest.raises(ArgValidationError) as exc_info:
        authorize("file_controller", "action=list", source="user")
    assert exc_info.value.code == CODE_INVALID_ARGS


def test_errors_do_not_echo_secrets() -> None:
    with pytest.raises(ArgValidationError) as exc_info:
        validate_args(
            "file_controller",
            {"action": 0, "token": SECRET, "api_key": GEMINI_LIKE},
        )
    message = str(exc_info.value)
    assert SECRET not in message
    assert GEMINI_LIKE not in message
    assert "token" not in message or SECRET not in message

    with pytest.raises(ArgValidationError) as unknown_source:
        authorize(
            "web_search",
            {"query": SECRET},
            source="attacker",
        )
    assert SECRET not in str(unknown_source.value)
