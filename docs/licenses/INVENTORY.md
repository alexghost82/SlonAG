# License inventory

Detailed working notes for `THIRD_PARTY_LICENSES.md`.
Source of package names: `requirements.txt` at the Wave 0 base (unpinned).
License lookup date: 2026-08-15, via PyPI JSON and selected upstream LICENSE files.

**This modernization must not claim that the product is commercially ready.**

## 1. Source project

`readme.md` states:

> Personal and non-commercial use only.
> Licensed under **Creative Commons BY-NC 4.0**.

Recorded terms:

- License name: Creative Commons Attribution-NonCommercial 4.0 International
- Short name as in `readme.md`: CC BY-NC 4.0
- URL cited by `readme.md`: https://creativecommons.org/licenses/by-nc/4.0/
- There is no root `LICENSE` file in this tree.
- This inventory does not create a root `LICENSE` and does not grant commercial rights.

Commercial use is **not permitted** without a separate grant from the rights
holder or an independent rewrite of protected code. Deciding among commercial
license, rewrite, or personal/non-commercial-only use is a user decision and
is out of scope for Wave 0.

## 2. Method

1. Read `readme.md` (license section) and `requirements.txt` as read-only inputs.
2. Query `https://pypi.org/pypi/<name>/json` for each requirement line.
3. Where PyPI metadata was missing or contradictory, read the upstream LICENSE
   file. SPDX identifiers are used only when PyPI published that identifier or
   the license text was checked.
4. Mark remaining gaps `UNKNOWN — verify`.
5. Do not download models, voices, or datasets.
6. Do not contact external legal services.
7. Do not edit `readme.md`, `requirements.txt`, or application code.

`requirements.txt` has no version pins. Versions below are the PyPI default
versions observed on the lookup date and are **not** installed pins.

## 3. Package inventory

Every line from `requirements.txt` appears below.

| # | requirements.txt name | PyPI project | Observed version | License | SPDX (only if sourced) | Windows-only | Notes |
|---|---|---|---|---|---|---|---|
| 1 | sounddevice | sounddevice | 0.5.5 | MIT | MIT | no | PyPI `license_expression` |
| 2 | google-genai | google-genai | 2.18.1 | Apache-2.0 | Apache-2.0 | no | Supported Google GenAI SDK |
| 3 | google-generativeai | google-generativeai | 0.8.6 | Apache 2.0 | — | no | **Deprecated.** `google-genai` is the supported replacement. Requirements files are unchanged by this task. |
| 4 | pillow | pillow | 12.3.0 | MIT-CMU | MIT-CMU | no | Same project as row 15 |
| 5 | requests | requests | 2.34.2 | Apache-2.0 | Apache-2.0 | no | PyPI license field |
| 6 | beautifulsoup4 | beautifulsoup4 | 4.15.0 | MIT License | — | no | PyPI classifier: MIT License. SPDX not published on PyPI. |
| 7 | duckduckgo-search | duckduckgo-search | 8.1.1 | MIT License | — | no | PyPI classifier: MIT License. SPDX not published on PyPI. |
| 8 | playwright | playwright | 1.62.0 | Apache-2.0 | Apache-2.0 | no | Covers the Python package. Playwright browser downloads have separate licenses. |
| 9 | pyautogui | PyAutoGUI | 0.9.54 | BSD-3-Clause | BSD-3-Clause | no | PyPI says BSD. Three-clause text confirmed in https://github.com/asweigart/pyautogui/blob/master/LICENSE.txt |
| 10 | pyperclip | pyperclip | 1.11.0 | BSD-3-Clause | BSD-3-Clause | no | PyPI says BSD. Three-clause text confirmed in https://github.com/asweigart/pyperclip/blob/master/LICENSE.txt |
| 11 | pygetwindow | PyGetWindow | 0.0.9 | BSD-3-Clause | BSD-3-Clause | **yes** | PyPI says BSD. Three-clause text confirmed in https://github.com/asweigart/PyGetWindow/blob/master/LICENSE.txt |
| 12 | opencv-python | opencv-python | 5.0.0.93 | Apache 2.0 | — | no | Declared package license. Bundled native libraries / codecs: later review. |
| 13 | numpy | numpy | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | no | Recorded exactly as PyPI `license_expression` |
| 14 | mss | mss | 10.2.0 | MIT License | — | no | PyPI classifier: MIT License. SPDX not published on PyPI. |
| 15 | Pillow | pillow | 12.3.0 | MIT-CMU | MIT-CMU | no | Duplicate casing of `pillow` in `requirements.txt` |
| 16 | psutil | psutil | 7.2.2 | BSD-3-Clause | BSD-3-Clause | no | PyPI license field |
| 17 | comtypes | comtypes | 1.4.16 | MIT | MIT | **yes** | PyPI `license_expression` |
| 18 | pycaw | pycaw | 20251023 | MIT | MIT | **yes** | PyPI license fields empty. MIT confirmed in https://github.com/AndreMiras/pycaw/blob/master/LICENSE |
| 19 | win10toast | win10toast | 0.9 | MIT | MIT | **yes** | Upstream LICENSE is MIT. PyPI `license` field says BSD and conflicts with classifier `License :: OSI Approved :: MIT License`. |
| 20 | send2trash | Send2Trash | 2.1.0 | BSD-3-Clause | BSD-3-Clause | no | PyPI `license_expression` |
| 21 | youtube-transcript-api | youtube-transcript-api | 1.2.4 | MIT | — | no | PyPI license field MIT; classifier MIT License. SPDX not published on PyPI. |
| 22 | pywinauto | pywinauto | 0.6.9 | BSD 3-clause | — | **yes** | Recorded as published on PyPI (`BSD 3-clause`). SPDX not invented. |
| 23 | pyaudio | PyAudio | 0.2.14 | MIT | — | no | Python bindings. Native PortAudio is separate. SPDX not published on PyPI. |

## 4. Windows-only packages

Recorded as Windows-only for this project (see task W00-T02):

- `pygetwindow`
- `comtypes`
- `pycaw`
- `win10toast`
- `pywinauto`

`readme.md` also notes that some OS-specific dependencies are omitted from
`requirements.txt`. Those omitted packages are not listed here because they are
not in the current requirements file.

## 5. Deprecated Google SDK

`requirements.txt` currently lists both:

- `google-genai` — supported Google GenAI SDK
- `google-generativeai` — deprecated / legacy SDK

`google-genai` is the supported replacement. This task documents the overlap
only. It does **not** edit requirements files or migrate application imports.

## 6. Items marked for verification

| Item | Why |
|---|---|
| beautifulsoup4 SPDX | PyPI says "MIT License" without a SPDX field. Treat SPDX as `UNKNOWN — verify` if a machine-readable identifier is required. |
| duckduckgo-search SPDX | Same as above. |
| mss SPDX | Same as above. |
| youtube-transcript-api SPDX | Same as above. |
| pyaudio SPDX | Same as above. |
| pywinauto SPDX | PyPI text is "BSD 3-clause"; SPDX not recorded here. |
| opencv-python native extras | Package is Apache 2.0; bundled FFmpeg / codec licensing is `UNKNOWN — verify`. |
| playwright browser binaries | Python package is Apache-2.0; Chromium / Firefox / WebKit terms are `UNKNOWN — verify`. |
| pyaudio / PortAudio native | Bindings are MIT; native PortAudio distribution terms are `UNKNOWN — verify`. |
| Transitive dependencies | Only direct `requirements.txt` names are inventoried. |

No direct-requirement license was left entirely blank. Where metadata was
empty (`pycaw`) or contradictory (`win10toast`), the upstream LICENSE file was
used instead of inventing a value.

## 7. Open items for later waves

Do not download models or voices to close these items.

| Item | Wave hint | Status |
|---|---|---|
| Piper TTS implementation license | Wave 12 (`W12-T01`); decided 2026-08-15 | **Decided** — rhasspy/piper MIT + `ru_RU-dmitri-medium` MIT (dataset CC0); no download in this inventory |
| Model licenses | Local / hosted weights, including any future local LLM, STT, TTS, or vision models | Open — not inventoried |
| Voice licenses | Local voice files; Gemini prebuilt voices (for example Charon in current code); other TTS voices | Piper voice decided; others open — not inventoried |
| Dataset licenses | Training or runtime datasets | Open — not inventoried |
| Hosted API terms | Gemini, OpenRouter, and any later provider Terms of Service | Open — not a substitute for a legal review |
| Source-project commercial path | Personal / non-commercial only (CC BY-NC aligned) | **Decided 2026-08-15**; no commercial-ready claim |

## 8. Secrets and artifacts

This inventory contains no API keys, tokens, cookies, or other secret values.
No models, voices, wheels, or generated binaries were downloaded or stored.

## 9. Self-check

- [x] Every `requirements.txt` package name appears in section 3 (23 lines, including `pillow` and `Pillow`).
- [x] Documents do not claim the product is commercially ready.
- [x] CC BY-NC 4.0 constraint is explicit.
- [x] Commercial use is stated as not permitted without a separate grant or an independent rewrite.
- [x] Unverified SPDX / native extras are marked `UNKNOWN — verify`.
- [x] No root `LICENSE` file was created.
- [x] No secret material is included.
