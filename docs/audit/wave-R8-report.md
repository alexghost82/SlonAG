# WAVE R8 — MCP / Browser / OS / Files

**WAVE:** R8  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-033 | MCP `invoke_tool` | CONFIRM auto-approved when `approval_required` was false | Always return `approval_required`. MCP cannot bypass SafetyPolicy. |
| SLON-033 | MCP descriptions / output | Tool text treated as trusted | Descriptions prefixed `[UNTRUSTED MCP DESCRIPTION]`; output truncated. |
| SLON-033 | FS `_safe_relative` / symlink walk | Prefix/`relative_to` + macOS `/var`→`/private/var` false escape | `Path.resolve()` + `is_relative_to`. Ancestor prefix symlinks allowed only if they contain the workspace; user symlink to foreign file still denied. |
| SLON-033 | Browser | Web content not marked untrusted | `runtime.browser.mark_web_content` / `WEB_CONTENT_TRUST=UNTRUSTED`. |

## REMOVED LEGACY

- Silent MCP CONFIRM auto-approve path.

## TESTS

| Command | Result |
| --- | --- |
| `python -m pytest tests/security/test_mcp_fs_r8.py tests/test_filesystem_security.py tests/unit/mcp_client/test_mcp_integration.py -q` | **59 passed** |

`tests/test_filesystem_security.py` was red at R0 (macOS `/var` symlink). It is green after the ancestor-symlink fix.

## SECURITY

- Unknown MCP tools fail closed (`UnknownToolError`).
- Builtin `shell_exec` is not replaced by MCP name collision.
- Page/MCP text is DATA.

## MIGRATIONS

None.

## KNOWN LIMITATIONS

- Playwright Chromium missing on this machine — browser integration suite still hardware/runtime dependent.
- Clipboard/desktop OS control not newly exercised.

## RUNTIME VERIFICATION STILL REQUIRED

- Full suite (in flight after R7).
- Real Playwright + malicious page injection.

## COMMITS

Recorded after commit.
