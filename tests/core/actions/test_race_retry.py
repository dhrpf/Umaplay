from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

import core.actions.race as race_module
from core.actions.race import RaceFlow


class DummyWaiter:
    def __init__(
        self,
        *,
        click_when_responses: Optional[List[Tuple[bool, Optional[Dict[str, Any]]]]] = None,
        seen_responses: Optional[List[Tuple[Dict[str, Any], bool]]] = None,
    ) -> None:
        self._click_iter = iter(click_when_responses or [])
        self._seen_responses = seen_responses or []
        self.try_click_once_calls: List[Dict[str, Any]] = []
        self.seen_calls: List[Dict[str, Any]] = []

    def click_when(self, **kwargs):
        try:
            result = next(self._click_iter)
        except StopIteration:
            if kwargs.get("return_object"):
                return False, None
            return False
        if kwargs.get("return_object"):
            return result
        return result[0]

    def try_click_once(self, **kwargs):
        self.try_click_once_calls.append(kwargs)
        return False

    def seen(self, **kwargs):
        self.seen_calls.append(kwargs)
        for matcher, value in self._seen_responses:
            target_texts = matcher.get("texts")
            requested_texts = kwargs.get("texts")
            if target_texts == requested_texts:
                return value
        return False


def _make_test_flow(waiter: DummyWaiter) -> RaceFlow:
    flow: RaceFlow = RaceFlow.__new__(RaceFlow)
    flow.ctrl = object()
    flow.ocr = None
    flow.yolo_engine = None
    flow.waiter = waiter
    flow._banner_matcher = None
    flow._race_result_counters = {
        "loss_indicators": 0,
        "retry_clicks": 0,
        "retry_skipped": 0,
        "wins_or_no_loss": 0,
    }
    return flow


def test_attempt_try_again_retry_clicks_once(monkeypatch):
    waiter = DummyWaiter(
        click_when_responses=[
            (True, {"xyxy": (0, 100, 0, 200)}),
        ]
    )
    flow = _make_test_flow(waiter)

    times = [0.0, 0.1]

    def fake_time():
        return times.pop(0) if times else 1.0

    monkeypatch.setattr(race_module.time, "time", fake_time)
    monkeypatch.setattr(race_module.time, "sleep", lambda *_: None)

    assert flow._attempt_try_again_retry() is True
    assert flow._race_result_counters["retry_clicks"] == 1


def test_handle_retry_transition_exits_on_view_results(monkeypatch):
    waiter = DummyWaiter(
        seen_responses=[
            ({"texts": ("VIEW RESULTS",)}, True),
        ]
    )
    flow = _make_test_flow(waiter)

    timeline = [0.0]

    def fake_time():
        timeline[0] += 0.1
        return timeline[0]

    monkeypatch.setattr(race_module.time, "time", fake_time)
    monkeypatch.setattr(race_module.time, "sleep", lambda *_: None)

    flow._handle_retry_transition()

    assert any(
        call.get("texts") == ("VIEW RESULTS",) for call in waiter.seen_calls
    )
