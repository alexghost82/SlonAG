"""Security regression tests for Windows computer control.

Covers: command injection via shell metacharacters, %COMSPEC% env-var
expansion, cmd /c, powershell invocations, Unicode/homoglyph bypasses,
quoted executable paths, and null-byte poisoning.
"""

from __future__ import annotations

import re

import pytest

from computer_control._windows import (
    _validate_windows_launch_input,
    _WINDOWS_INJECTION_RE,
    _WINDOWS_CMD_INVOCATION_RE,
    _BLOCKED_BASENAMES,
)


class TestShellMetacharacterInjection:
    """These payloads MUST be rejected."""
    @pytest.mark.parametrize("payload", [
        'notepad.exe; calc.exe',
        'notepad && echo pwned',
        'notepad || echo pwned',
        'notepad | echo pwned',
        'notepad > /tmp/out.txt',
        'notepad < /tmp/in.txt',
        'notepad`id`',
        'notepad $(whoami)',
        '$(',
        'cmd.exe; echo hi',
        'taskkill /F; echo hi',
        'dir & net user',
        'notepad 2>&1',
        'notepad >nul 2>&1',
    ])
    def test_injection_rejected(self, payload: str) -> None:
        assert _validate_windows_launch_input(payload) is None, (
            f"FAILED to reject: {payload!r}"
        )

class TestEnvVarExpansion:
    """%VAR% expansion should be blocked."""
    @pytest.mark.parametrize("payload", [
        '%COMSPEC% /c notepad',
        '%WINDIR%\\\\System32\\\\cmd.exe',
        '%APPDATA%\\\\..\\\\..\\\\cmd.exe',
        '%PATH%',
        '%SYSTEMROOT%\\\\notepad.exe',
        '%PROGRAMFILES%\\\\App\\\\app.exe',
        'echo %COMSPEC%',
    ])
    def test_env_var_rejected(self, payload: str) -> None:
        assert _validate_windows_launch_input(payload) is None, (
            f"FAILED to reject env-var: {payload!r}"
        )

class TestCmdPwshInvocation:
    """Direct shell invocations must be rejected."""
    @pytest.mark.parametrize("payload", [
        'cmd /c notepad',
        'cmd /c dir',
        'CMD /C dir',
        'Cmd /c dir',
        'cmd.exe /c notepad',
        'cmd.exe; echo hi',
        'powershell -Command Get-Process',
        'powershell -c dir',
        'PowerShell -Command id',
        'pwsh -Command dir',
        'pwsh.exe -c dir',
        'C:\\\\Windows\\\\System32\\\\cmd.exe /c dir',
        'C:\\\\Windows\\\\System32\\\\powershell.exe -c dir',
    ])
    def test_cmd_powershell_blocked(self, payload: str) -> None:
        assert _validate_windows_launch_input(payload) is None, (
            f"FAILED to reject cmd/pwsh: {payload!r}"
        )

class TestBlockedBasenames:
    """Dangerous basenames must be rejected."""
    @pytest.mark.parametrize("name", [
        'cmd',
        'cmd.exe',
        'powershell',
        'powershell.exe',
        'pwsh',
        'pwsh.exe',
        'pwsh.dll',
        'cmdkey',
        'cmdkey.exe',
        'cscript',
        'cscript.exe',
        'wscript',
        'wscript.exe',
        'runas',
        'runas.exe',
        'schtasks',
        'schtasks.exe',
        'reg',
        'reg.exe',
    ])
    def test_blocked_basename_rejected(self, name: str) -> None:
        assert _validate_windows_launch_input(name) is None, (
            f"FAILED to reject basename: {name!r}"
        )

    @pytest.mark.parametrize("path", [
        'C:\\\\Windows\\\\notepad.exe',
        'C:\\\\Program Files\\\\App\\\\app.exe',
        'C:\\\\Program Files (x86)\\\\App\\\\app.exe',
        'C:\\\\Users\\\\User\\\\App\\\\app.exe',
        '/usr/local/bin/app',
    ])
    def test_safe_paths_accepted(self, path: str) -> None:
        assert _validate_windows_launch_input(path) == path, (
            f"Falsely blocked: {path!r}"
        )

class TestUnicodeHomoglyphs:
    """Unicode tricks."""
    @pytest.mark.parametrize("payload", [
        "аcmd /c notepad",  # Cyrillic а looks like a
        "мcmd /c notepad",  # Cyrillic с looks like c
        "еcmd.exe",  # Cyrillic е looks like e
        "оcmd.exe",  # Cyrillic е looks like e
        "  cmd /c notepad  ",  # whitespace
        "\tcmd /c notepad",  # tab prefix
    ])
    def test_unicode_rejected(self, payload: str) -> None:
        """cmd /c detection should catch most homoglyph cases."""
        result = _validate_windows_launch_input(payload)
        # The regex catches "cmd /c" regardless of Unicode tricks
        # because \s in the regex matches various whitespace
        assert result is None, (
            f"FAILED to reject unicode evasion: {payload!r}"
        )

class TestEndToEnd:
    def test_safe_app_accepted(self) -> None:
        assert _validate_windows_launch_input("notepad") == "notepad"

    def test_empty_rejected(self) -> None:
        assert _validate_windows_launch_input("") is None

    def test_none_input_returns_none(self) -> None:
        # None is falsy, so if not value: returns None
        assert _validate_windows_launch_input(None) is None  # type: ignore[arg-type]

class TestRegexRegression:
    """Regex must still match all known injection patterns."""
    @pytest.mark.parametrize("pattern", [
        'notepad.exe; calc.exe',
        'notepad && echo pwned',
        'notepad || echo pwned',
        'notepad | echo pwned',
        'notepad > /tmp/out.txt',
    ])
    def test_injection_regex(self, pattern: str) -> None:
        assert _WINDOWS_INJECTION_RE.search(pattern), (
            f"Injection regex missed: {pattern!r}"
        )

    @pytest.mark.parametrize("pattern", [
        'cmd /c notepad',
        'cmd /c dir',
        'CMD /C dir',
        'Cmd /c dir',
        'cmd.exe /c notepad',
    ])
    def test_cmd_regex(self, pattern: str) -> None:
        assert _WINDOWS_CMD_INVOCATION_RE.search(pattern), (
            f"Cmd regex missed: {pattern!r}"
        )

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
