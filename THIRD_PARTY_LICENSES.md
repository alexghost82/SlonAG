# Third-party licenses — Slon

This file is a license registry for the current tree. It is not a grant of rights
and it does not replace the source-project terms in `readme.md`.

**This modernization must not claim that the product is commercially ready.**
Commercial distribution is a user decision and is out of scope for this inventory.

## Source project

| Item | Record |
|---|---|
| License as stated in `readme.md` | Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0) |
| Official text | https://creativecommons.org/licenses/by-nc/4.0/ |
| Root `LICENSE` file | None in this tree |
| Permitted use (as stated) | Personal and non-commercial use only |

Commercial use of this project is **not permitted** without a separate grant from
the rights holder or an independent rewrite of protected code. Choosing among
those options is outside this task.

## How to read this registry

- Python package names match `requirements.txt` exactly, including the duplicate
  `pillow` / `Pillow` lines.
- License names come from PyPI metadata and, where noted, from the upstream
  `LICENSE` file. SPDX identifiers are recorded only when the source used that
  identifier or the license text was checked.
- Unverified licenses are marked `UNKNOWN — verify`.
- This file does not change `requirements.txt` or application code.

## Current Python dependencies

| Package | License | Notes |
|---|---|---|
| sounddevice | MIT | PyPI `license_expression`: MIT |
| google-genai | Apache-2.0 | Supported Google GenAI SDK. PyPI `license_expression`: Apache-2.0 |
| google-generativeai | Apache 2.0 | **Deprecated.** `google-genai` is the supported replacement. This inventory does not change requirements files. |
| pillow | MIT-CMU | Same PyPI project as `Pillow` below |
| requests | Apache-2.0 | PyPI license field: Apache-2.0 |
| beautifulsoup4 | MIT License | PyPI classifier: MIT License |
| duckduckgo-search | MIT License | PyPI classifier: MIT License |
| playwright | Apache-2.0 | Python package only. Browser binaries downloaded by Playwright have separate terms. |
| pyautogui | BSD-3-Clause | PyPI says BSD; three-clause text confirmed in upstream `LICENSE.txt` |
| pyperclip | BSD-3-Clause | PyPI says BSD; three-clause text confirmed in upstream `LICENSE.txt` |
| pygetwindow | BSD-3-Clause | **Windows-only in this project.** PyPI says BSD; three-clause text confirmed in upstream `LICENSE.txt` |
| opencv-python | Apache 2.0 | Declared package license. Bundled native codecs may need a later review. |
| numpy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Recorded as PyPI `license_expression` (includes vendored components) |
| mss | MIT License | PyPI classifier: MIT License |
| Pillow | MIT-CMU | Duplicate of `pillow` in `requirements.txt`; one PyPI project |
| psutil | BSD-3-Clause | PyPI license field: BSD-3-Clause |
| comtypes | MIT | **Windows-only in this project.** PyPI `license_expression`: MIT |
| pycaw | MIT | **Windows-only in this project.** PyPI metadata empty; MIT confirmed in upstream `LICENSE` |
| win10toast | MIT | **Windows-only in this project.** Upstream `LICENSE` is MIT. PyPI `license` field says BSD and conflicts with the MIT classifier — treat the field as unreliable. |
| send2trash | BSD-3-Clause | PyPI `license_expression`: BSD-3-Clause |
| youtube-transcript-api | MIT | PyPI classifier: MIT License |
| pywinauto | BSD 3-clause | **Windows-only in this project.** PyPI license field: BSD 3-clause |
| pyaudio | MIT | Python bindings. Native PortAudio is a separate dependency. |

## Windows-only packages

The following `requirements.txt` entries are Windows-only for this project:

- `pygetwindow`
- `comtypes`
- `pycaw`
- `win10toast`
- `pywinauto`

They remain listed because this inventory mirrors the current requirements file.
A later wave may split platform requirements; that work is out of scope here.

## Open items for later waves

These items are **not** resolved by this inventory. Do not download models or
voices to complete them.

| Item | Status |
|---|---|
| Piper TTS implementation license | **Decided 2026-08-15** — runtime rhasspy/piper (MIT); voice `ru_RU-dmitri-medium` (MIT). Implementation task `W12-T01`; do not download models in this inventory. |
| Model licenses (local or hosted weights) | Open — not inventoried; no models downloaded |
| Voice licenses (local voices, Gemini prebuilt voices, other TTS voices) | Piper voice decided above; other voices still open — not inventoried; no voices downloaded |
| Dataset licenses | Open — not inventoried |

## What this file does not do

- It does not grant commercial rights.
- It does not add a root `LICENSE` file.
- It does not claim commercial readiness.
- It does not rotate, record, or require API keys.
- It does not change dependency pins or replace `google-generativeai`.
