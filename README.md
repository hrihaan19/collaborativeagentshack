# Domino

**SYNTHETIC DEMO — NOT A CLINICAL MATCHING TOOL.**
Nothing here diagnoses, determines real suitability, enrolls donors, collects health data, or schedules surgery. All records are fictional fixtures. `K0–K3` are software fixture ids, not HLA, not crossmatch.

Domino is an open-source, synthetic-data-only prototype of **cross-border kidney-exchange discovery**: three hospitals in three countries with **no shared registry** and no legal path to pool patient records. Each hospital runs a Flower agent over its own local records. A neutral coordinator asks the hospitals for screening results *through Flower*, builds an exchange graph, proposes cycles/chains, and every hospital's clinician must approve the exact proposal. A clinician hold invalidates the plan and forces a re-solve.

| Role | Where | What runs |
|---|---|---|
| Hospital A — Palo Alto, United States | M1 | `flower-supernode` (outbound only) + ClientApp + local console `127.0.0.1:8010` |
| Hospital B — Tel Aviv, Israel | M2 | same |
| Hospital C — Abu Dhabi, United Arab Emirates | M3 | same |
| Neutral coordinator | Nebius VM (fallback: M1) | `flower-superlink` + ServerApp (solver) + API `:8001` + dashboard `:8501` + QR page `:8020` |

Hospitals expose **zero inbound ports**. Their only network connection is an outbound Flower connection to the SuperLink. The coordinator cannot reach a hospital except through a Flower message, and a hospital never runs a server anyone can call. That is the answer to "why not HTTP".

Flower version: **`flwr==1.39.0`** (pinned in `pyproject.toml`; the start scripts refuse to run on any other version).

---

## Status report (honest labels)

Labels: **VERIFIED** (observed running) · **IMPLEMENTED-UNVERIFIED** (code exists, not observed end-to-end) · **SIMULATED** · **RULE-BASED FALLBACK** · **SINGLE-HOST ONLY**.

### VERIFIED — on one machine (SINGLE-HOST ONLY), 2026-09-29

Run in the development container with a real `flower-superlink` + three real `flower-supernode` processes (ports 9094–9096) + `flwr run` of the ServerApp. Evidence: `evidence/flower-roundtrip-single-host.json`, `evidence/flower-smoke-latest.json`, `evidence/*.png`.

1. **Real Flower round trip.** One `SCREEN_REQUEST` (JSON bytes in a `ConfigRecord` inside a `RecordDict`/`Message`) to three SuperNodes started with `--node-config 'hospital-id="A|B|C" ...'`; three schema-valid `SCREEN_RESPONSE` replies whose `hospital_id` comes from the node config. Flower `run_id`, node ids, and message ids are logged in the audit (`state/coordinator/audit.jsonl`) and shown on the dashboard. Hospital ↔ node mapping observed: A=177454847794493307, B=10112905917919172903, C=17707147246835290796 (ids differ on every fresh SuperNode).
2. **Fixtures + local search.** Each hospital seeds its own records; every hospital's local-only search finds 0 exchanges.
3. **Cross-hospital screening → graph → solver.** Edges `P1→P2, P1→W4, P2→P3, P3→P1`; exactly one three-cycle `P1→P2→P3→P1`; plan with canonical SHA-256 hash; `PLAN_PREPARE` acked by all three hospitals.
4. **Human gate.** New private note at Hospital B → `P2` becomes `REVIEW_REQUIRED` by rule → plan parked in `REVIEW_PENDING` (approvals void) → clinician clicks **HOLD** in B's local console → coordinator's next `REVIEW_STATUS` poll sees `HOLD` → plan `INVALIDATED (CLINICIAN_HOLD)` → re-solve → `NO_FEASIBLE_EXCHANGE` (only `P3→P1, P1→W4` remain).
5. **Presenter button → `DONOR_ACTIVATION` through Flower → Hospital C activates fixture `N0` → fresh screening → edge `N0→P3` → chain `N0→P3→P1→W4` (3 recipients), `P2` stays held.
6. **Signatures.** Each hospital console signs the exact plan hash (Ed25519, `cryptography`); coordinator verifies three signatures against keys pinned on first sight → `PLAN_FINALIZE` re-queries every involved hospital once → `APPROVED_FOR_SIMULATED_COORDINATION`.
7. **Dashboard** (one HTML page, inline SVG): graph from plan/graph state, state machine, approval matrix, sanitized Flower message audit. **Chain reveal** animates the plan's edges in plan order, exactly once per plan, on the REVEAL button (state lives in `ui.json`, so every open dashboard reveals the same plan once).
8. **QR page** (`/qr` → `/add?token=…`): single-use 10-minute token, rate-limited, only ever activates `N0`. Token path verified with curl; phone/LAN not verified.
9. **Tests** T02–T05 pass (`pytest -q tests` → `5 passed`). Flower smoke test passes (`scripts/flower-smoke-test.py`).

### IMPLEMENTED-UNVERIFIED

- **Three-machine deployment** (Nebius + M1 + M2 + M3). The scripts read everything from `.env`; only single-host was run. **Cross-machine verification is OUTSTANDING.**
- **Local model** (`domino/hospital/llm.py`, Ollama direct call, ≤3 calls, 8 s timeout, JSON output, one repair). No Ollama was available here; every run used **RULE-BASED FALLBACK**, and the rule caught the note regardless (that is the design).
- Public-key pinning across restarts of the coordinator (keys are pinned per coordinator state; `reset-demo.sh` keeps them).

### SIMULATED

- Everything clinical. "APPROVED_FOR_SIMULATED_COORDINATION" is a software state; nothing is scheduled.
- Hospital "records" are the fixtures below. Compatibility is a toy rule (ABO table + marker-not-in-blocked-set). Missing data → `UNKNOWN`, never positive.

### Design decision: ServerApp/ClientApp, not AgentApp

Timeboxed check (~6 min) of `flwr.agentapp` in 1.39.0: `AgentApp` is a *coordinator-side*, prompt-driven app (`AgentSession.prompt`, model-facing `AgentGrid` tools, driven by `flwr chat`). It is not a mechanism for running bounded hospital logic on a remote SuperNode. Hospital logic therefore lives inside the **Flower `ClientApp`** (`domino/hospital/client_app.py` → `domino/hospital/logic.py`), executing on the SuperNode when it pulls a message. No sidecar, no HTTP between ClientApp and hospital logic. AgentApp and ServerApp/ClientApp assumptions are not mixed.

### Cut today (as instructed)

TLS / SuperNode auth (**INSECURE DEV MODE**, `--insecure`), reservations, watchdogs, offline-hospital handling, replay protection beyond unique message ids, signature expiry/revocation, React, tracing, Gate-0 audit. One protocol addition beyond the eight listed types: `DONOR_ACTIVATION` (the coordinator has no path to a hospital except Flower, so the presenter/QR beat needs a message; the ClientApp only ever activates the inactive fixture `N0`).

Do not claim: clinical validity, HIPAA, federated learning, sponsor endorsement.

---

## Fixtures (exact; all fictional; names never leave the hospital)

| Vertex | Hospital | Recipient | Paired donor |
|---|---|---|---|
| P1 | A | Maria, ABO A, blocked {K0,K2} | ABO B, marker K1 |
| P2 | B | James, ABO B, blocked {} | ABO A, marker K2 |
| P3 | C | Elena, ABO A, blocked {K3} | ABO A, marker K3 |
| W4 | B | Noah, ABO B, blocked {}, **no donor** (chain end only) | — |
| N0 | C | — | non-directed, ABO A, marker K0, **inactive until activated** |

ABO: O→O,A,B,AB · A→A,AB · B→B,AB · AB→AB. Toy compatible = ABO allowed AND donor marker ∉ recipient's private blocked set.

Expected: initial edges `P1→P2, P1→W4, P2→P3, P3→P1`, one three-cycle. After P2 hold: `P3→P1, P1→W4`, no exchange. After N0: `+N0→P3`, chain `N0→P3→P1→W4`. T05 perturbs N0 to ABO AB so it screens `NOT_CANDIDATE` everywhere and no chain appears.

## Protocol

`domino/protocol.py` — pydantic, `extra='forbid'`, bounded lengths. Envelope: `schema_version, run_id, round_id, message_id, message_type, created_at, record_version`. Types: `SCREEN_REQUEST, SCREEN_RESPONSE, REVIEW_STATUS, PLAN_PREPARE, PLAN_ACK, PLAN_APPROVAL, PLAN_FINALIZE, REFUSAL` (+ `DONOR_ACTIVATION`). **One egress class** (`HospitalEgress`) for everything that leaves a hospital: opaque tokens, hospital id, donor ABO + marker, result `{TOY_CANDIDATE, NOT_CANDIDATE, UNKNOWN}`, availability `{AVAILABLE, HOLD, REVIEW_REQUIRED}`, record versions, signatures (+ public key). Never names, recipient ABO, blocked sets, note text, prompts, model output, exception text.

Screening is two Flower rounds: (1) every hospital announces its active donors + vertex statuses; (2) the coordinator sends the donor catalog to every hospital, and each hospital evaluates each donor against **its own** recipients. Only the hospital that owns the recipient may assert an edge into it. A held pair offers nothing and is not screened.

## Human gate

- HOLD is local, immediate, set only in that hospital's console; the coordinator only *learns* of it on its next `REVIEW_STATUS` poll (every `POLL_SECONDS`, default 5) and cannot override it.
- Any new note → `REVIEW_REQUIRED` by rule → plan `REVIEW_PENDING`, approvals cleared. Any record change on an involved vertex → plan `INVALIDATED` → re-solve.
- Approval = the console signs the exact plan hash (Ed25519). The console refuses to sign if the local record versions changed since the plan.
- Before finalization the coordinator re-queries every involved hospital once (`PLAN_FINALIZE`).
- No AI code path can reach `/api/approve`, set `AVAILABLE`, or clear a `HOLD`. The optional model returns `{suggest_review, reason_code}` to the console and nothing else.

## Running it

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # flwr==1.39.0 + deps; same on every machine
cp .env.example .env               # set COORDINATOR_HOST (Nebius IP) and PUBLIC_URL
pytest -q tests                    # T02-T05
```

**Coordinator (Nebius VM, or M1 as fallback):**
```bash
scripts/start-coordinator.sh
# = flower-superlink --insecure --fleet-api-address 0.0.0.0:9092 --host 0.0.0.0 --port 9093 --disable-runtime-dependency-installation
#   + uvicorn domino.coordinator.api:app on 0.0.0.0:8001 / 8501 / 8020
#   + flwr run . domino -c 'state-dir="<abs>/state/coordinator" poll-seconds=5 round-timeout=60'
```
In flwr 1.39 the Control API is HTTP on `--host/--port` (9093 here; the old `--control-api-address` flag is deprecated) and connections are read from `$FLWR_HOME/config.toml` (`[superlink.domino]`), which the scripts write. Runtime dependency installation is disabled: every machine pre-installs this package.

**Each hospital (M1/M2/M3):**
```bash
scripts/start-hospital-a.sh    # or -b / -c
# = flower-supernode --insecure --superlink $COORDINATOR_HOST:9092 --host 127.0.0.1 --port 9094 \
#     --node-config 'hospital-id="A" partition-id=0 num-partitions=3 state-dir="<abs>/state/hospital-a"'
#   + uvicorn domino.hospital.console:app --host 127.0.0.1 --port 8010
```
Node-config string values must be quoted (`hospital-id="A"`), otherwise flwr rejects the config.

**Single host (SINGLE-HOST ONLY):** `scripts/dev-single-host.sh` (SuperNodes 9094–9096, consoles 8010–8012). Then `python scripts/flower-smoke-test.py`.

**Seed / reset:** `scripts/seed-demo.sh` (this machine's hospitals), `scripts/reset-demo.sh` (re-seed + coordinator RESET job). `scripts/stop-all.sh`.

Demo choreography: `docs/demo-script.md`.

## Layout

```
domino/protocol.py               envelopes + the one egress schema
domino/fixtures.py               fixtures + toy compatibility rule
domino/hospital/client_app.py    Flower ClientApp (hospital agent entrypoint)
domino/hospital/logic.py         screening / plan handling (runs inside the ClientApp)
domino/hospital/store.py         private records, readiness rules, hold, plans, versions
domino/hospital/console.py|html  local human gate, 127.0.0.1
domino/hospital/llm.py           optional Ollama note reader (RULE-BASED FALLBACK otherwise)
domino/hospital/keys.py          Ed25519 per hospital
domino/coordinator/server_app.py Flower ServerApp: job loop -> Flower rounds -> state
domino/coordinator/solver.py     cycles (2-3) + chains (<=3 recipients), disjoint selection, validation
domino/coordinator/graph.py      egress -> exchange graph
domino/coordinator/state.py      state machine, audit, jobs, ui.json
domino/coordinator/api.py        API + dashboard + QR/add pages
domino/coordinator/static/       dashboard.html, qr.html, add.html
scripts/                         start-*, seed, reset, stop, dev-single-host, flower-smoke-test
tests/test_solver.py             T02-T05
evidence/                        captured proof from the single-host run
```
