# Domino — 3-minute table demo

**Say first:** "Everything on screen is synthetic. This is not a clinical matching tool."

Setup before judges arrive: federation up (`start-coordinator.sh` on Nebius, `start-hospital-{a,b,c}.sh` on M1/M2/M3, or `dev-single-host.sh` as fallback), `reset-demo.sh` run, dashboard open on the big screen, Hospital B console open on M2, Hospital C console on M3, a box of dominoes lined up P1→P2→P3 in a loop and N0→P3→P1→W4 in a line, QR page ready on a tablet.

| t | Beat | Click | What to say |
|---|---|---|---|
| 0:00 | The problem | — | "Three hospitals, three countries, no shared registry. They can't pool records. The 2021 Israel–Abu Dhabi exchange had no shared registry either." |
| 0:20 | Local search | point at consoles | "Each hospital searches alone: zero exchanges. Names never leave the machine." |
| 0:35 | Screen via Flower | dashboard **SCREEN & SOLVE** | "The coordinator on Nebius can't call a hospital. It sends a Flower message; the hospital's SuperNode pulls it, screens locally, and only tokens and results come back." Show the audit filling with run id / node ids. |
| 0:55 | The cycle | **REVEAL PLAN**, tip the three dominoes | "Three hospitals, one three-way cycle. A plan hash is now on every hospital's screen." |
| 1:15 | The human gate | B console: add a note to P2 → **HOLD** | "A new note at Tel Aviv flags review by rule — a local model can suggest it, it can't decide. The clinician holds. Nobody can override that." Dashboard: REVIEW_PENDING → INVALIDATED → NO_FEASIBLE_EXCHANGE. Knock the P2 domino out of the loop. |
| 1:50 | New donor | tablet QR (or presenter button **ADD A FICTIONAL DONOR**) | "A fictional non-directed donor appears in Abu Dhabi. Fresh screening through Flower…" |
| 2:10 | The chain | **REVEAL PLAN**, tip N0→P3→P1→W4 | "A chain: three recipients, three countries, P2 still held." |
| 2:30 | Approvals | APPROVE on A, B, C consoles | "Each hospital signs the exact plan hash. Three verified signatures; the coordinator re-queries everyone once more." Dashboard: APPROVED_FOR_SIMULATED_COORDINATION. |
| 2:50 | Close | — | "Nothing was diagnosed, nobody was enrolled, nothing is scheduled. The point is the shape: local data, Flower messages, human gates." |

If Nebius is unreachable: coordinator on M1 (`COORDINATOR_HOST` in `.env`), say so. If cross-machine networking fails: `dev-single-host.sh`, and say "SINGLE-HOST ONLY" out loud.

Recovery: `scripts/reset-demo.sh` on every machine (hospitals re-seed locally; coordinator clears its plan). If the ServerApp heartbeat pill turns red on the dashboard, re-run `flwr run . domino -c 'state-dir="…"'` on the coordinator.
