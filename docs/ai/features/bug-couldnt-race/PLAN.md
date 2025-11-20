---
status: plan_ready
---

# PLAN

## Objectives
- Ensure Unity Cup race-day flow never strands the bot after failed skill purchases; flow must reliably return to Lobby/Raceday before racing.
- RaceFlow should distinguish between recoverable UI hiccups and hard failures so the agent can retry or skip without raising RuntimeError unless truly necessary.
- ADB runs should receive controller-aware Waiter/timeout tuning so button detection and retries match Steam/Scrcpy reliability.
- Add instrumentation/tests to confirm the bot can (1) skip skills, (2) buy successfully, and (3) recover when confirmations are missing, all without crashing.

## Steps (general; not per-file)
### Step 1 — Harden SkillsFlow exit & reporting
**Goal:** Guarantee that finishing the skills screen always lands back on the lobby/raceday context with an accurate success signal.
**Actions (high level):**
- Teach `SkillsFlow.buy()` to treat `_confirm_learn_close_back_flow()` as authoritative—track partial failures, re-issue BACK clicks, and return a tri-state result (e.g., success, no-buy, failed-exit).
- Add localized recovery routines (extra BACK clicks, optional detection of `RACE`/`LOBBY` markers) before handing control back to the agent.
- Update Unity Cup agent’s Raceday branch to honor the richer result (skip racing or trigger fallback if exit failed).
**Affected files (expected):**
- `core/actions/skills.py`
- `core/actions/unity_cup/agent.py`
- (Possibly) `core/actions/ura/agent.py` for symmetry
**Quick validation:**
- Run Unity Cup in ADB with forced skills-buy failure (e.g., remove confirmations) and confirm the log shows graceful exit + race skip instead of RuntimeError.

### Step 2 — Classify RaceFlow failures & add safe recovery
**Goal:** Prevent blanket `RuntimeError` by returning structured failure reasons and retrying or backing out safely.
**Actions (high level):**
- Extend `RaceFlow.run()` to emit enums/reasons (no race card, buttons missing, abort requested, consecutive penalty) instead of bare bool.
- In Unity Cup/URA agents, interpret these reasons: retry once, set skip guards, or only raise for unrecoverable cases (e.g., repeated aborts).
- Add logging hooks so we can trace which stage failed in ADB runs.
**Affected files (expected):**
- `core/actions/race.py`
- `core/actions/unity_cup/agent.py`
- `core/actions/ura/agent.py`
**Quick validation:**
- Simulate missing race button (e.g., by lowering YOLO conf) and confirm the agent logs a skip + continues training instead of crashing.

### Step 3 — Tune Waiter/ADB interaction
**Goal:** Improve detection reliability for ADB-driven sessions.
**Actions (high level):**
- Introduce controller-aware Waiter settings (timeouts, poll intervals, OCR thresholds) when Settings indicate ADB.
- Revisit `allow_greedy_click` usage for TRY AGAIN / Confirm buttons so single-candidate paths don’t over-rely on OCR.
- Ensure `SkillsFlow` scroll heuristics detect ADB controller explicitly (treat like Android for drag gestures).
**Affected files (expected):**
- `core/utils/waiter.py`
- `core/actions/race.py` (call-site overrides)
- `core/actions/skills.py`
- `core/controllers/adb.py` (if new hints/flags needed)
**Quick validation:**
- Run Unity Cup in ADB and capture logs showing reduced `[waiter] timeout` spam for TRY AGAIN / CONFIRM sequences.

### Step 4 — Instrumentation & tests
**Goal:** Lock in behavior with telemetry and regression coverage.
**Actions (high level):**
- Add structured log fields (e.g., `race_failure_reason`, `skills_exit_status`).
- Create targeted unit/integration tests for `SkillsFlow` result handling and `RaceFlow` failure classification (mock Waiter/controller as needed).
- Consider a lightweight scenario script that simulates the Raceday→Skills→Race chain with fake detections to reproduce bug-couldnt-race quickly.
**Affected files (expected):**
- `core/actions/skills.py`
- `core/actions/race.py`
- `tests/` (new or updated test modules)
**Quick validation:**
- Run new tests plus existing suite; confirm logs include the new telemetry fields during manual runs.

### Step 5 — Finalization
**Goal:** Stabilize, verify, and close out.
**Actions (high level):**
- Run lint/type checks and scenario smoke tests (Unity Cup ADB + Steam) end-to-end.
- Clean up temporary instrumentation or feature flags if permanent.
- Update release notes / TODOs if needed.
**Quick validation:**
- Full Unity Cup career succeeds in both Steam and ADB with skills buys enabled/disabled.

## Test Plan
- **Unit:**
  - `SkillsFlow.buy()` tri-state return handling (mock waiter/controller, simulate confirm/button absence).
  - `RaceFlow.run()` reason classification; ensure enums map to expected log output.
- **Integration/E2E:**
  - Unity Cup Raceday with forced skill purchase success/failure.
  - Unity Cup planned race with missing race card to verify skip guard.
  - ADB end-to-end career run ensuring no `RuntimeError("Couldn't race")` surfaces.
- **UX/Visual:**
  - Observe Skills UI to ensure extra BACK/Confirm clicks don’t mis-tap; verify no lingering overlays.

## Verification Checklist
- [ ] Lint and type checks pass locally
- [ ] Unity Cup race-day flow behaves across Steam/ADB
- [ ] Logs show new telemetry fields without PII
- [ ] Feature flags or settings toggles behave as intended (if added)

## Rollback / Mitigation
- Revert the specific PR touching skills/race flows.
- Temporarily disable Unity Cup automation or fall back to previous release if regression observed.
- For emergencies, set a config flag to skip skills buys and suppress planned races until patches reapply.

## Open Questions (if any)
- Should we introduce a dedicated feature flag to gate the new race failure handling, or is immediate rollout acceptable?
- Do we need user-configurable thresholds for Waiter/ADB tuning, or can we rely on static heuristics?
