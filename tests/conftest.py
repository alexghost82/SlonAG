"""Shared fixtures for SlonAG tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Root of the SlonAG project (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root(project_root: Path) -> Path:
    """Root of the SlonAG project (alias for project_root)."""
    return project_root

@pytest.fixture(scope="session", autouse=True)
def _mock_tkinter():
    """Mock tkinter, pyautogui, PIL, and related deps for headless Linux environments
    where tkinter is not installed.  This prevents ModuleNotFoundError / SystemExit
    in computer_control.capabilities which imports pyautogui at module level."""
    import sys, types

    # Build a minimal tkinter mock before anything can import it
    tk = types.ModuleType("tkinter")
    tk.TkVersion = 8.6
    tk.filedialog = types.ModuleType("tkinter.filedialog")
    tk.colorchooser = types.ModuleType("tkinter.colorchooser")
    tk.messagebox = types.ModuleType("tkinter.messagebox")
    for sub in (tk.filedialog, tk.colorchooser, tk.messagebox):
        setattr(sub, "askopenfilename", lambda *a, **k: None)
        setattr(sub, "asksaveasfilename", lambda *a, **k: None)
        setattr(sub, "showwarning", lambda *a, **k: None)
        setattr(sub, "showinfo", lambda *a, **k: None)
        setattr(sub, "showerror", lambda *a, **k: None)
        setattr(sub, "askyesno", lambda *a, **k: True)
        setattr(sub, "askokcancel", lambda *a, **k: True)
        setattr(sub, "askyesnocancel", lambda *a, **k: True)
    # Also put sub-modules on the main tkinter module so nested imports work
    sys.modules["tkinter"] = tk
    for name in ("tkinter.filedialog", "tkinter.colorchooser", "tkinter.messagebox"):
        sys.modules[name] = getattr(tk, name.rsplit(".", 1)[-1])

    if "PIL" not in sys.modules:
        pil = types.ModuleType("PIL")
        sys.modules["PIL"] = pil
        pil_image = types.ModuleType("PIL.Image")
        pil_image.Image = type("Image", (), {"open": lambda *a, **k: None})
        sys.modules["PIL.Image"] = pil_image

    # Stub pyautogui entirely so code that checks for it doesn't crash
    pg = types.ModuleType("pyautogui")
    pg.click = lambda *a, **k: None
    pg.typewrite = lambda *a, **k: None
    pg.hotkey = lambda *a, **k: None
    pg.screenshot = lambda *a, **k: None
    pg.locateOnScreen = lambda *a, **k: None
    pg.locateCenterOnScreen = lambda *a, **k: None
    pg.moveTo = lambda *a, **k: None
    pg.moveTo = lambda *a, **k: None
    pg.scroll = lambda *a, **k: None
    pg.onMouseUp = lambda *a, **k: None
    pg.onScroll = lambda *a, **k: None
    pg.onDrag = lambda *a, **k: None
    pyautogui_keys = ("size", "onScreen", "getPointOnScreen", "position", "dragTo")
    for name in pyautogui_keys:
        setattr(pg, name, lambda *a, **k: None)
    sys.modules["pyautogui"] = pg
    # Stub pymsgbox (also depends on tkinter)
    pm = types.ModuleType("pymsgbox")
    pm.alert = lambda *a, **k: "OK"
    pm.confirm = lambda *a, **k: "OK"
    pm.prompt = lambda *a, **k: ""
    pm.password = lambda *a, **k: ""
    sys.modules["pymsgbox"] = pm

    # Stub other optional deps that may crash without display
    for mod in ("mss", "cv2", "sounddevice", "psutil"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
