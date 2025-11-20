---
date: 2025-11-20T18:00:00-05:00
topic: bug-couldnt-race
status: research_complete
---

# RESEARCH — bug-couldnt-race

## Research Question
Why does the Unity Cup career bot in ADB mode sometimes fail with a `RuntimeError("Couldn't race…")` / hang around the skills-buy phase, and how do the race and skills flows interact so we can harden recovery back to the lobby/race screen?

## Summary (≤ 10 bullets)
- **Race error source:** `RuntimeError("Couldn't race" / "Couldn't race or stopped due to dangerouse action")` is raised only from the URA/Unity Cup agents when `RaceFlow.run()` returns `False`.
- **Failure modes in RaceFlow:** `RaceFlow.run()` returns `False` if it cannot: (a) find a race square, (b) click a green `RACE` button in the list, or (c) complete the post-race lobby flow (notably when `View Results` / `RACE` cannot be resolved).
- **Skills flow is separate but adjacent:** On Unity Cup `Raceday`, the agent *first* runs a skills-buy flow, then immediately calls `RaceFlow.run()`. If skills flow leaves the UI in an unexpected state, race detection can fail and propagate as `Couldn't race`.
- **Skills confirmation path is brittle:** `SkillsFlow.buy()` assumes the Confirm → Learn → Close → Back sequence exists when *any* BUY click was attempted, but it ignores the boolean return of `_confirm_learn_close_back_flow()`, so failed confirmations still report `True` to the agent.
- **When no skills are matched:** If no BUY clicks occur, `SkillsFlow.buy()` presses `BACK` via `Waiter.click_when()` and logs `[skills] No matching skills found to buy.` — this part is robust and visible in the provided log.
- **Waiter semantics:** `Waiter.click_when()` only uses the fast single/bottom-candidate click path when `allow_greedy_click=True`; otherwise it relies purely on OCR text matching and can time out even when a single green button is present but text OCR is noisy.
- **Retry on race losses:** Race losses are handled inside `RaceFlow.lobby()` via `TRY AGAIN` probing (`_attempt_try_again_retry()` and `_handle_retry_transition()`), driven entirely by `Waiter.click_when()`; if buttons are not recognized, the race flow can abort with `False`.
- **ADB-specific dimension:** ADB mode uses `ADBController` under the same `IController` interface as Steam/Scrcpy. The race and skills codepaths are controller-agnostic, but scroll/click behavior differs slightly (e.g., `SkillsFlow._scroll_once` only treats `ScrcpyController` as “android”, so ADB is in the generic path that still maps to ADB swipes).
- **Logs confirm skills → race sequence:** In the provided log, Unity Cup `Raceday` opens Skills with ~770 pts, attempts purchases, ends with `[skills] No matching skills found to buy.` and returns cleanly, followed by race flows and goal/end-of-career handling — the crash trace with `Couldn't race` is in an earlier, truncated part of the same log.
- **Key risk:** The combination of (1) optimistic success reporting from `SkillsFlow.buy()` and (2) strict failure behavior in `RaceFlow.run()` means any UI drift around Skills or Raceday lobbies can surface as a hard `RuntimeError` instead of a recoverable skip.

## Detailed Findings (by area)

### Area: Unity Cup agent race/skills orchestration
- **Why relevant:** This is where the Unity Cup scenario decides when to open the Skills screen, when to race, and how to react to failures (`RuntimeError`).
- **Files & anchors (path:line_start–line_end):**
  - `core/actions/unity_cup/agent.py:105–207` — main `AgentUnityCup.run()` loop, screen classification and unknown screen handler.
  - `core/actions/unity_cup/agent.py:326–429` — `screen == "Raceday"` branch: skills gate, `lobby._go_skills()`, `skills_flow.buy()`, then race-day `self.race.run(...)` with `from_raceday=True`.
  - `core/actions/unity_cup/agent.py:544–646` — handling `outcome == "TO_RACE"` from lobby, including `Couldn't race` logging for G1, planned, and fans races (non-Raceday path).
- **Cross-links:**
  - Uses `RaceFlow` from `core/actions/race.py` (`self.race.run(...)`).
  - Uses shared `Waiter` (`self.waiter`) for all clicks.
  - Uses `SkillsFlow` from `core/actions/skills.py` (`self.skills_flow.buy(self.skill_list)`).
  - Reads planning and date info from `LobbyFlowUnityCup` (`core/actions/unity_cup/lobby.py`).

**Behavior notes:**
- On `screen == "Raceday"`, the agent:
  - Refreshes skill memory and extracts skill points.
  - If `skill_pts >= _minimum_skill_pts` (from preset/config) and `skill_list` not empty, it may open skills:
    - Applies interval/points-delta gating (`Settings.SKILL_CHECK_INTERVAL`, `Settings.SKILL_PTS_DELTA`).
    - If gate passes or `_first_race_day`, calls `self.lobby._go_skills()` then `self.skills_flow.buy(self.skill_list)`.
  - After skills, it decides if the race is pre-debut, then calls `self.race.run(..., from_raceday=True, reason=...)`.
  - If `self.race.run(...)` returns `False`, it *immediately raises* `RuntimeError("Couldn't race or stopped due to dangerouse action")`.

- On `screen == "Lobby"` (non-Raceday), the agent also calls `self.race.run(...)` in several branches (G1, planned race, fans), but here failures are logged and the agent usually backs out to Lobby instead of raising.

### Area: RaceFlow (race-day automation & retry)
- **Why relevant:** `RaceFlow.run()` is the only source for `ok=False` in race-day flows, which then causes agents to raise `RuntimeError("Couldn't race…")`.
- **Files & anchors:**
  - `core/actions/race.py:68–144` — `_ensure_in_raceday()`: enters Raceday from Lobby, handles consecutive-race penalty (with `ConsecutiveRaceRefused`), uses `Waiter.click_when()` and `Waiter.seen()`.
  - `core/actions/race.py:288–681` — `_pick_race_square()`: locates race squares and stars, resolves desired/planned races, uses OCR + template matching, returns `(square, need_click)` or `(None, True)`.
  - `core/actions/race.py:686–941` — `RaceFlow.lobby()`: post-race lobby handler — `View Results` resolution, `RACE` clicking, skip-loop, `TRY AGAIN` detection, and final `NEXT`/`race_after_next` exit.
  - `core/actions/race.py:1054–1173` — `RaceFlow.run()`: end-to-end race routine, including RACE list click, pre-lobby gating, strategy setting, and final call to `self.lobby()`.
- **Cross-links:**
  - Uses `Waiter` (`core/utils/waiter.py`) for all UI interactions.
  - Uses YOLO via `collect()` and OCR for race card/title text.
  - Depends on `RaceIndex` for planned race name resolution.
  - Uses `ActiveButtonClassifier` to determine whether `View Results` is active.

**Key failure points that cause `ok=False`:**
- `_ensure_in_raceday()` returns `False` after failing to see `race_square`/handle penalty (in non-Raceday callers; Unity Cup Raceday sets `from_raceday=True` so it always accepts penalties and won’t raise `ConsecutiveRaceRefused`).
- `_pick_race_square()` returns `None` (no square with ≥2 stars or desired/planned race not found) → `run()` logs `"race square not found"` and returns `False`.
- RACE list click fails:
  - `Waiter.click_when(classes=("button_green",), texts=("RACE",), ...)` in `run()` returns `False` → logs warning and returns `False`.
- Pre-lobby never recognized:
  - `run()` waits up to ~14s for `button_change`; if it never appears, the loop silently exits, and we still fall through to `self.lobby()` while not truly in the race lobby. From there, `lobby()` may fail to find `View Results` / `RACE` and return `False`.
- Post-race lobby aborts:
  - `lobby()` aborts with `False` when it cannot find `View Results` or `RACE` after configured retries, logging explicit errors.

**Log correlation:**
- In the provided log snippet, we see the healthy path:
  - `run(): [race] RaceDay begin (prioritize_g1=False, is_g1_goal=False) | reason='Training policy → race'`
  - Pre-lobby and skip-loop logs, `TRY AGAIN` probing (`race_try_again_try` timeouts), and then
  - `logger_uma.info("[race] RaceDay flow finished.")` → `True` returned.
- The `RuntimeError("Couldn't race…")` mentioned in the report corresponds to the *other* branch where one of the failure points above returns `False`.

### Area: SkillsFlow (skills screen automation)
- **Why relevant:** Skills-buying runs immediately before race-day `RaceFlow.run()` in Unity Cup, and the user report explicitly describes hangs when the bot “keeps trying to click to purchase” and then finds no confirmation button.
- **Files & anchors:**
  - `core/actions/skills.py:30–58` — `SkillsFlow.__init__`: injects `IController`, `OCRInterface`, `IDetector`, shared `Waiter`, loads `ActiveButtonClassifier`, `SkillMatcher`, and `SkillMemoryManager`.
  - `core/actions/skills.py:63–152` — `SkillsFlow.buy()`: high-level buying loop, early-stop logic, and final confirm/back path.
  - `core/actions/skills.py:330–477` — `_scan_and_click_buys()`: single-pass detector over `skills_square` + `skills_buy`, OCR title matching against `skill_list`, skill memory integration.
  - `core/actions/skills.py:502–555` — `_confirm_learn_close_back_flow()`: Confirm → Learn → Close → Back sequence using `Waiter.click_when()`.
  - `core/actions/skills.py:557–609` — `_focus_nudge()` and `_scroll_once()`: scroll behavior; note `ScrcpyController` special-casing.
- **Cross-links:**
  - Used by `AgentUnityCup` and URA agents (both lobby and FinalScreen flows).
  - Uses `Waiter` to click Confirm/Learn/Close/Back, sharing the same YOLO/OCR stack as race flows.
  - Uses `SkillMemoryManager` to avoid double-buys and remember grades (`○` vs `◎`).

**Behavior & risks:**
- `buy()` accumulates `purchases_made` and sets `any_clicked=True` whenever a BUY button is tapped (based purely on controller click calls, not on verifying that the game actually registered a selection).
- When `any_clicked` is `True` at the end of the scroll loop, it unconditionally calls `_confirm_learn_close_back_flow()` and returns `True`, *ignoring the return value* of the confirm flow.
- `_confirm_learn_close_back_flow()` itself:
  - Requires `CONFIRM` then `LEARN` green buttons to exist; if either is not detected within its timeouts, it logs a warning and returns `False` without trying to force navigation back to Lobby/Raceday.
  - Similarly, failure to find `CLOSE` or `BACK` results in `False`, leaving the agent wherever it was when the click sequence stopped.
- If a skill BUY click is physically off (e.g., due to ADB coordinate drift or an inactive button that passes the classifier), it’s possible to:
  - Have `any_clicked=True`, so `buy()` reports `True` to the agent.
  - But have no pending selections on-screen, so `CONFIRM`/`LEARN` never appear; `_confirm_learn_close_back_flow()` times out, logs a warning, returns `False`, and leaves the UI in an indeterminate state.
  - The agent then continues as if skills were bought and immediately calls `RaceFlow.run()` from a potentially wrong screen, which can lead to `ok=False` and `RuntimeError("Couldn't race…")`.

**Log correlation:**
- In the supplied snippet around 04:03–04:07, we see a *clean* no-buy case:
  - `_scan_and_click_buys()` repeatedly logs matcher diagnostics with `ok: False` for all targets, or `skipping 'Standard Distance ○' (already purchased)` based on skill memory.
  - Eventually `buy()` logs `[skills] No matching skills found to buy.` and returns `False`.
  - Agent logs `[agent] Skills bought: False` and continues into race/end-of-career logic normally.
- The user-reported problematic behavior (no confirmation button, stuck in Skills, followed by `Couldn't race`) would require a different path: at least one BUY click attempted, but no CONFIRM/LEARN sequence available.

### Area: Waiter + ADB controller
- **Why relevant:** Both skills and race flows are completely driven by `Waiter` over YOLO/OCR detections, and in ADB mode all clicks/scrolls are routed through `ADBController` rather than Scrcpy/Steam.
- **Files & anchors:**
  - `core/utils/waiter.py:38–122` — `Waiter` class and `click_when()` public API.
  - `core/utils/waiter.py:230–281` — `seen()` helper.
  - `core/utils/waiter.py:283–347` — `try_click_once()` helper.
  - `core/utils/waiter.py:353–449` — `_snap()`, `_is_forbidden()`, `_pick_by_text()`, and utilities.
  - `core/controllers/adb.py:16–120` — `ADBController.__init__()`, ADB connectivity, screen-size detection.
  - `core/controllers/adb.py:160–224` — `scroll()` mapped to ADB `input swipe`.
  - `core/controllers/adb.py:229–281` — `screenshot()`, `click()`, and input primitives.
- **Cross-links:**
  - `Waiter` is instantiated once per agent (`PollConfig`) and used by both race and skills flows.
  - `SkillsFlow._scroll_once()` treats only `ScrcpyController` specially; ADB uses the “PC path” that still works because `ADBController.scroll()` interprets signed deltas as swipes.

**Behavior & risks:**
- `click_when()` cascade:
  - Path 1: if there is exactly one candidate and `allow_greedy_click=True`, it clicks immediately, *without OCR*, unless `forbid_texts` block it.
  - Path 2: if `prefer_bottom` and `allow_greedy_click`, it picks the bottom-most candidate, again without OCR unless forbidden.
  - Path 3: only when `texts` is provided and OCR is configured, it uses `_pick_by_text()`.
- This means that whenever callers pass `allow_greedy_click=False` (e.g., for some `TRY AGAIN` and Unknown-screen handlers), Waiter *must* rely on OCR matching, which can be unstable in ADB runs (different font rendering, resolution, or capture noise).
- In the log snippet, repeated `[waiter] timeout after 0.30s (tag=race_try_again_try)` lines illustrate OCR-based misses on `TRY AGAIN` detection.
- ADB’s `screenshot()` and `click()` are synchronous ADB `screencap` and `input tap` calls with extra latency; combined with tight timeouts in `click_when()` (e.g., 0.3s in `_attempt_try_again_retry()`), transient UI states are more likely to be missed in ADB than in Steam/Scrcpy.

## 360° Around Target(s)
- **Target file(s):**
  - `core/actions/unity_cup/agent.py` — scenario main loop, Raceday logic, and `RuntimeError("Couldn't race…")` raising sites.
  - `core/actions/race.py` — `RaceFlow` navigation, race card selection, lobby handling, and retry.
  - `core/actions/skills.py` — `SkillsFlow` buying and confirmation/back flow.
  - `core/utils/waiter.py` — unified detector/click orchestrator.
  - `core/controllers/adb.py` — ADB-backed controller implementation.

- **Dependency graph (depth 2):**
  - `core/actions/unity_cup/agent.py`
    - Depends on `core/actions/unity_cup/lobby.py` (`LobbyFlowUnityCup`).
    - Depends on `core/actions/race.py` (`RaceFlow`).
    - Depends on `core/actions/skills.py` (`SkillsFlow`).
    - Uses `core/utils/waiter.PollConfig` and `Waiter`.
    - Uses `core/utils/event_processor.UserPrefs` and `core/utils/race_index.unity_cup_preseason_index` for planning.
  - `core/actions/race.py`
    - Uses `core.utils.waiter.Waiter` for `click_when()`, `seen()`, and `try_click_once()`.
    - Uses `core.controllers.base.IController` (runtime can be Steam/Scrcpy/ADB).
    - Uses `core.perception.yolo` (`collect()`) and OCR for card titles, badges, and buttons.
    - Uses `core.utils.race_index.RaceIndex` for planned race resolution.
    - Uses `core.perception.is_button_active.ActiveButtonClassifier` for `View Results` activation.
  - `core/actions/skills.py`
    - Uses `Waiter` for Confirm/Learn/Close/Back clicks.
    - Uses `IController`, `OCRInterface`, `IDetector`.
    - Uses `SkillMatcher` and `SkillMemoryManager`.
    - Uses `ActiveButtonClassifier` for BUY-button activeness in each `skills_square`.
  - `core/utils/waiter.py`
    - Uses `IController` to perform clicks.
    - Uses `IDetector` via `yolo_engine.recognize()` to get detections.
    - Uses `OCRInterface` for text disambiguation and forbid-text logic.
  - `core/controllers/adb.py`
    - Implements `IController` methods using ADB (`adb devices`, `screencap`, `input tap`, `input swipe`).
    - Screen size detection is based on `wm size` / `dumpsys display` fallbacks.

## Open Questions / Ambiguities
- **Where to harden recovery from a bad Skills → Race transition?**  
  Options:
  1. Add robust escape hatches *inside* `SkillsFlow._confirm_learn_close_back_flow()` (e.g., if CONFIRM/LEARN are missing after BUY clicks, fall back to pressing `BACK` a few times and explicitly return the user to Lobby/Raceday before reporting success/failure).
  2. Add a post-`buy()` sanity check in the agent (`AgentUnityCup.run` Raceday branch) to confirm the screen has returned to `Raceday` or `Lobby` before calling `RaceFlow.run()`, and skip racing if not.
  3. Treat `buy()` return value as tri-state (e.g., `enum {NONE, SUCCESS, FAILED_EXIT}`) instead of plain bool, so the agent can distinguish “no skills”, “bought and exited”, and “UI ambiguous”.

- **How to distinguish between “safe to skip” race failures and truly fatal ones?**  
  Right now, *any* `False` from `RaceFlow.run()` on `Raceday` leads to a `RuntimeError`. Should we:
  - (a) only raise for clear logic errors (e.g., `ConsecutiveRaceRefused` with conflicting settings) and otherwise treat failures as soft (e.g., back to Lobby, skip_race flag, continue training)?
  - (b) gate fatal errors behind a config flag (e.g., `STRICT_RACE_FAILURES`)?
  - (c) add richer error codes from `RaceFlow.run()` (e.g., `NO_RACE_FOUND`, `BUTTONS_MISSING`, `ABORT_REQUESTED`) instead of bare booleans?

- **Is ADB-specific tuning needed for Waiter timeouts and OCR thresholds?**  
  The current timeouts (e.g., 0.3s for `TRY AGAIN`, ~3s for Confirm) were likely tuned for Steam/Scrcpy. In ADB mode, should we:
  - (a) scale timeouts by a per-controller factor (e.g., longer timeouts for ADB)?
  - (b) relax OCR thresholds (`threshold`, `forbid_threshold`) or rely more on greedy clicks when there is a single candidate?
  - (c) add controller-aware overrides (e.g., ADB-specific `PollConfig`) for race/skills flows?

## Suggested Next Step
- Draft `docs/ai/features/bug-couldnt-race/PLAN.md` with:
  - A per-file change plan for `AgentUnityCup`, `SkillsFlow`, and `RaceFlow` detailing where to add recovery logic and safer error propagation.
  - Concrete strategies for ADB-specific Waiter tuning (timeouts, thresholds, and greedy vs OCR behavior).
  - A small regression test checklist: reproduce ADB Unity Cup runs with (1) no skills to buy, (2) some skills bought successfully, and (3) deliberately broken skill titles/thresholds to simulate no-Confirm states, verifying that the bot always returns to Lobby/Raceday without raising `RuntimeError("Couldn't race…")`.
