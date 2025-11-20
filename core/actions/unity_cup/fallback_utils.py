# core/actions/unity_cup/fallback_utils.py
from __future__ import annotations

from time import sleep
from typing import List, Optional, Tuple, TYPE_CHECKING

from core.perception.extractors.state import find_best
from core.settings import Settings
from core.types import DetectionDict
from core.utils.logger import logger_uma

if TYPE_CHECKING:  # pragma: no cover
    from core.actions.unity_cup.agent import AgentUnityCup

FALLBACK_PATIENCE_STAGE_1 = 6
FALLBACK_PATIENCE_STAGE_2 = 12
MIN_FALLBACK_CONF = 0.15


def _threshold_pair_golden() -> Tuple[float, float]:
    primary = max(0.2, float(Settings.UNITY_CUP_GOLDEN_CONF or 0.6))
    relaxed = max(
        MIN_FALLBACK_CONF,
        float(Settings.UNITY_CUP_GOLDEN_RELAXED_CONF or 0.35),
    )
    if relaxed >= primary:
        relaxed = max(MIN_FALLBACK_CONF, primary - 0.05)
    return primary, relaxed


def _threshold_pair_race() -> Tuple[float, float]:
    primary = max(0.25, float(Settings.UNITY_CUP_RACE_DAY_CONF or 0.65))
    relaxed = max(
        MIN_FALLBACK_CONF,
        float(Settings.UNITY_CUP_RACE_DAY_RELAXED_CONF or 0.4),
    )
    if relaxed >= primary:
        relaxed = max(MIN_FALLBACK_CONF, primary - 0.05)
    return primary, relaxed


def _thresholds_for(
    primary: float,
    relaxed: float,
    *,
    patience: int,
    force_relaxed: bool = False,
) -> List[float]:
    thresholds = [primary]
    if force_relaxed or patience >= FALLBACK_PATIENCE_STAGE_1:
        thresholds.append(relaxed)
    if force_relaxed or patience >= FALLBACK_PATIENCE_STAGE_2:
        thresholds.append(max(MIN_FALLBACK_CONF, relaxed - 0.1))

    ordered: List[float] = []
    seen = set()
    for thr in thresholds:
        thr = max(MIN_FALLBACK_CONF, float(thr))
        if thr in seen:
            continue
        seen.add(thr)
        ordered.append(thr)
    return ordered


def _find_adaptive_detection(
    dets: List[DetectionDict],
    name: str,
    *,
    primary: float,
    relaxed: float,
    patience: int,
    force_relaxed: bool = False,
) -> Tuple[Optional[DetectionDict], Optional[float]]:
    thresholds = _thresholds_for(
        primary,
        relaxed,
        patience=patience,
        force_relaxed=force_relaxed,
    )
    for conf_min in thresholds:
        candidate = find_best(dets, name, conf_min=conf_min)
        if candidate:
            return candidate, conf_min
    return None, None


def _log_fallback_event(
    target: str,
    *,
    reason: str,
    detection: DetectionDict,
    threshold: float,
    patience: int,
    via_waiter: bool,
) -> None:
    logger_uma.info(
        "[UnityCup] Fallback %s handled (reason=%s, det_conf=%.2f, threshold=%.2f, patience=%d, via_waiter=%s)",
        target,
        reason,
        float(detection.get("conf", 0.0)),
        threshold,
        patience,
        via_waiter,
    )


def maybe_click_golden(
    agent: "AgentUnityCup",
    dets: List[DetectionDict],
    *,
    reason: str,
    force_relaxed: bool = False,
) -> bool:
    primary, relaxed = _threshold_pair_golden()
    detection, threshold = _find_adaptive_detection(
        dets,
        "button_golden",
        primary=primary,
        relaxed=relaxed,
        patience=getattr(agent, "patience", 0),
        force_relaxed=force_relaxed,
    )
    if not detection or threshold is None:
        return False
    agent.ctrl.click_xyxy_center(detection["xyxy"], clicks=1)
    _log_fallback_event(
        "button_golden",
        reason=reason,
        detection=detection,
        threshold=threshold,
        patience=getattr(agent, "patience", 0),
        via_waiter=False,
    )
    agent.patience = 0
    agent.claw_turn = 0
    sleep(0.25)
    return True


def maybe_handle_race_card(
    agent: "AgentUnityCup",
    dets: List[DetectionDict],
    *,
    reason: str,
    allow_waiter_probe: bool,
    force_relaxed: bool = False,
) -> bool:
    primary, relaxed = _threshold_pair_race()
    detection, threshold = _find_adaptive_detection(
        dets,
        "race_race_day",
        primary=primary,
        relaxed=relaxed,
        patience=getattr(agent, "patience", 0),
        force_relaxed=force_relaxed,
    )
    if not detection or threshold is None:
        return False

    via_waiter = False
    if allow_waiter_probe:
        via_waiter = bool(
            agent.waiter.click_when(
                classes=("button_green",),
                texts=("GO", "RACE", "NEXT"),
                prefer_bottom=True,
                allow_greedy_click=False,
                timeout_s=0.6,
                tag=f"unity_{reason}_go_probe",
            )
        )

    if not via_waiter:
        agent.ctrl.click_xyxy_center(detection["xyxy"], clicks=1)
        sleep(0.25)

    _log_fallback_event(
        "race_race_day",
        reason=reason,
        detection=detection,
        threshold=threshold,
        patience=getattr(agent, "patience", 0),
        via_waiter=via_waiter,
    )
    agent.patience = 0
    return True


def handle_unknown_low_conf_targets(
    agent: "AgentUnityCup", dets: List[DetectionDict]
) -> bool:
    if maybe_click_golden(agent, dets, reason="unknown"):
        return True
    if maybe_handle_race_card(
        agent,
        dets,
        reason="unknown",
        allow_waiter_probe=True,
    ):
        return True
    return False
