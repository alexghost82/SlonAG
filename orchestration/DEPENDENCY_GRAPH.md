# DEPENDENCY_GRAPH — Slon

## Wave graph

```text
W0 --> W1 --> W2 --> W3 --> W4 --> W5 --> W7 --> W8 --> W9 --> W10 --> W11
                               \-> W6 --/              \------------/
```

## Task graph

| Task | depends_on | blocks | parallel_with |
|---|---|---|---|
| W00-T01 | orchestration bootstrap | W01-* | W00-T02, W00-T03 |
| W00-T02 | orchestration bootstrap | W01-*, commercial claims | W00-T01, W00-T03 |
| W00-T03 | orchestration bootstrap | W01-T04 | W00-T01, W00-T02 |
| W01-T01 | W00 integrated | W02-T02, W04-T02 | W01-T02, W01-T03, W01-T04 |
| W01-T02 | W00 integrated | W03-*, W05-T01 | W01-T01, W01-T03, W01-T04 |
| W01-T03 | W00 integrated | later shared harness changes | W01-T01, W01-T02, W01-T04 |
| W01-T04 | W00-T03 | none in Wave 1 | W01-T01, W01-T02, W01-T03 |
| W02-T01 | W01 | later UI string migration | W02-T02 |
| W02-T02 | W01 | W03-* | W02-T01 |
| W03-T01 | W02-T02 | W04-T01 | W03-T02, W03-T03, W03-T04 |
| W03-T02 | W02-T02 | W04-T01 | W03-T01, W03-T03, W03-T04 |
| W03-T03 | W02-T02 | W04-T01 | W03-T01, W03-T02, W03-T04 |
| W03-T04 | W02-T02 | W04-T01, W05-T01 | W03-T01, W03-T02, W03-T03 |
| W04-T01 | W03 | W04-T02, W04-T03, W05, W06 | none |
| W04-T02 | W04-T01 | W05, W08 | W04-T03 |
| W04-T03 | W04-T01 | later UI work | W04-T02 |
| W05-T01 | W04 | W07, W08 | W05-T02, W05-T03 |
| W05-T02 | W04 | W07, offline suite | W05-T01, W05-T03 |
| W05-T03 | W04 (Piper deferred to W12-T01) | W07, offline suite | W05-T01, W05-T02 |
| W06-T01 | W04 | W07 | W06-T02, W06-T03 |
| W06-T02 | W04 | W07 | W06-T01, W06-T03 |
| W06-T03 | W04 | W07, iOS memory | W06-T01, W06-T02 |
| W07-T01 | W05, W06 | W07-T02..T05, W08 | none |
| W07-T02 | W07-T01 | W08 | W07-T03, W07-T04, W07-T05 |
| W07-T03 | W07-T01 | W08 | W07-T02, W07-T04, W07-T05 |
| W07-T04 | W07-T01 | W08 | W07-T02, W07-T03, W07-T05 |
| W07-T05 | W07-T01 | W08 | W07-T02, W07-T03, W07-T04 |
| W08-T01 | W07 | W09, W11 | none |
| W09-T01 | W08 | iOS and later API routes | none initially |
| W10-* | W09 | W11 | after DesignSystem + Networking |
| W11-T01 | W08, W10 integrated | beta readiness | none (serial) |
| W11-* | W08, W10 | beta | selected verification tasks |
| W12-T01 | W05-T03 + Piper decision 2026-08-15 | richer local TTS | W12-T02 |
| W12-T02 | W09 bind mock + LAN decision 2026-08-15 | same-LAN remote | W12-T01 |

## Wave 0 contracts

### W00-T01

- Input: plan §7.1 ignore list.
- Output: `.gitignore`, `.gitattributes`.
- Tests: integrator `git check-ignore` for secret and runtime paths.

### W00-T02

- Input: `readme.md` license statement, `requirements.txt`.
- Output: `THIRD_PARTY_LICENSES.md`, `docs/licenses/**`.
- Tests: document review; no commercial-ready claim.

### W00-T03

- Input: read-only OpenClaw working tree and Cursor-workspace untracked list.
- Output: `docs/audit/user-changes.md`.
- Tests: inventory completeness; no secret values copied.
