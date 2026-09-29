# Domino — the 3–5 minute demo (17:15)

Projector on Mac 4: `scripts/start-projector.sh` → open **http://localhost:7800/projector**, press **F** for fullscreen. Mac 3 (Riverbend) opens **/console/riverbend**, Macs 1–2 open **/console/alder** and **/console/harbor** (same server, LAN URL). A tablet shows **/give** via the QR on screen. Everything below is one press of **→** per beat.

**Say first:** "All patients, hospitals and medicine here are synthetic."

| Beat | Press | What happens | Say |
|---|---|---|---|
| 0 Title | — | Dark Northern California, three dim hospitals, "You are here" at Stanford. | "Three hospitals. Twelve families. No shared database." |
| 1 Meet them | → | Maria+Elena, James+Priya, Grace+Sam with blood chips and why they don't match. | "Every donor here would give a kidney to someone they love. None of them match." |
| 2 Alone | → | Each locked panel scans its own list: 0, 0, 0. | "Each hospital, alone: zero." |
| 3 The agents talk | → | Flower SuperGrid hub, packets out (compat · pair · donor B · 6 antigens) and back (H1 · compatible · high; R1 · not this week · infection). "reading 4 charts · 13 rulebook sections". Each hospital refuses the canary (patient names). Wire strip prints field names and bytes. | "Only yes or no crosses. Names, charts and rules stay home." |
| 3b Why agents | → | Keyword rules: measured score with the traps struck through; agent score from `docs/evidence/readiness-eval.json` (shows — until measured). | "Every hospital writes its own rules. Our agents read them where they live." |
| 4 The loop | → | Three arcs draw with couriers; counter 0→3; plan panel with the explanation and "Checked by code and by a second model ✓". | "Together: three transplants." |
| 5 The human | → | Riverbend console shows Grace's approval card with the rule (§1.1) and the chart line. **Surgeon on Mac 3 clicks "Ask others to hold until Oct 9".** Hold packets go out; Alder accepts, Harbor Point declines (donor availability); NO CONSENSUS; the plan re-forms as the swap, counter 3→2, "Grace keeps her place". (If nobody clicks: **S**.) | "A surgeon asked everyone to wait. One hospital couldn't, for a reason only it knows. The plan re-formed in seconds." |
| 6 The domino | → | QR appears. **A judge opens /give and presses the button** (fallback: **G**). Kidney at Stanford; "7 patients could receive this kidney. Only Kenji's chain keeps going"; five legs fall with couriers, counter ticks 2→7; Malik lights up as bridge donor. | "One stranger. Five more transplants. Three hospitals that never saw each other's files." |
| 7 The schedule | → | Agents chat: each hospital's constraint with its rulebook section; coordinator: "Mark's kidney leaves San Jose at 10:00 and reaches Sacramento at 12:00, inside Riverbend's cutoff." Friday timeline with the tightest leg in yellow. | "They shared 'works' and 'doesn't'. Not one calendar, not one chart." |
| 8 Close | → | Counter at 7, all arcs lit, audit line. | "No shared database. A person at every step. Seven people go home." |

**Keys:** → / Space next · ← back · R reset · S finish beat from script · G fire the chain · B Harbor Point offline/back · F fullscreen · 1/2/3 open consoles · M scripted ↔ live · H help.

**Modes (badge always tells the truth):** REHEARSAL = scripted, no network. LIVE = press M; on beats 3, 5, 6, 7 the projector runs `flwr run . supergrid --run-config phase=…` and draws only real `DOMINO_EVENT` lines; after 25 s of silence it finishes the beat from the script and the badge drops back to REHEARSAL. Replay mode is not built.

**If things go wrong:** R resets everything (consoles too). If a hold click was missed, S plays the negotiation from the script. If the room's Wi-Fi dies, stay in REHEARSAL — the story is identical.
