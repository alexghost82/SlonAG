# Piper TTS licenses (Slon)

Operator-facing notes for the optional local Piper engine.
**No binaries or ONNX models are committed to this repository.**

## Runtime (intended default)

| Item | Value |
|---|---|
| Project | [rhasspy/piper](https://github.com/rhasspy/piper) (archived MIT lineage) |
| Role | Local CLI invoked by `speech.tts.piper.PiperSpeechSynthesizer` |
| License | **MIT** |
| Distribution | User-supplied binary on `PATH` or explicit `binary_path` |
| Network | Engine makes **no** network calls; no API keys |

Do **not** treat OHF-Voice `piper1-gpl` as the project default. If an operator
installs only a GPL Piper binary, that license applies to *their* install and
must be recorded separately; this tree still documents rhasspy/piper (MIT) as
the intended runtime.

## Binary strategy (Apple Silicon / macOS)

Prefer one of:

1. Place an MIT rhasspy/piper binary at `models/piper/piper`, or
2. Install via Homebrew and ensure `piper` is on `PATH`, or
3. Build from source.

The historical **official macOS aarch64 release tarball** has been unreliable /
broken for some operators — do not treat it as the default install path.

## Default voice

| Field | Value |
|---|---|
| Voice id | `ru_RU-dmitri-medium` |
| Files | `ru_RU-dmitri-medium.onnx` + `ru_RU-dmitri-medium.onnx.json` |
| Upstream | https://huggingface.co/rhasspy/piper-voices (`ru/ru_RU/dmitri/medium/`) |
| Voice license | **MIT** |
| Training dataset | **CC0** (per upstream MODEL_CARD) |

## On-disk layout

Models live under gitignored repo-root `/models/` (or an absolute path):

```text
models/piper/ru_RU-dmitri-medium.onnx
models/piper/ru_RU-dmitri-medium.onnx.json
```

## Opt-in download (Wave 13)

`PiperSpeechSynthesizer` still never downloads. An **opt-in** helper exists:

```bash
python -m speech.tts download --consent
python -m speech.tts download --consent --dry-run
```

Library API: `speech.tts.download.download_piper_voice(consent=True, ...)`.
Without `consent=True` / `--consent`, no network I/O occurs. CI and unit tests
inject a fake `fetcher` and never hit Hugging Face. Missing files still raise
clear errors from the engine when download was not used.

## Project posture

Personal / non-commercial only (CC BY-NC aligned). MIT/CC0 voice assets are
compatible with that posture. This note does not grant commercial rights.
