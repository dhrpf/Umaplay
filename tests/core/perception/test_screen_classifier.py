from __future__ import annotations

from typing import Dict, Iterator

import pytest

from core.perception.analyzers.screen import classify_screen_unity_cup
from core.settings import Settings


def _det(name: str, conf: float = 0.5, box: tuple[int, int, int, int] | None = None) -> Dict:
    return {
        "name": name,
        "conf": conf,
        "xyxy": box or (0, 0, 10, 10),
    }


@pytest.fixture()
def restore_settings() -> Iterator[None]:
    snapshot = {
        "UNITY_CUP_GOLDEN_CONF": Settings.UNITY_CUP_GOLDEN_CONF,
        "UNITY_CUP_GOLDEN_RELAXED_CONF": Settings.UNITY_CUP_GOLDEN_RELAXED_CONF,
        "UNITY_CUP_RACE_DAY_CONF": Settings.UNITY_CUP_RACE_DAY_CONF,
        "UNITY_CUP_RACE_DAY_RELAXED_CONF": Settings.UNITY_CUP_RACE_DAY_RELAXED_CONF,
    }
    yield
    for key, value in snapshot.items():
        setattr(Settings, key, value)


def test_classify_inspiration_relaxed_threshold(restore_settings: None) -> None:
    Settings.UNITY_CUP_GOLDEN_CONF = 0.9
    Settings.UNITY_CUP_GOLDEN_RELAXED_CONF = 0.45

    dets = [_det("button_golden", conf=0.5)]

    screen, info = classify_screen_unity_cup(dets)

    assert screen == "Inspiration"
    assert info == {"has_golden": True}


def test_classify_race_day_relaxed_threshold(restore_settings: None) -> None:
    Settings.UNITY_CUP_RACE_DAY_CONF = 0.85
    Settings.UNITY_CUP_RACE_DAY_RELAXED_CONF = 0.5

    dets = [
        _det("race_race_day", conf=0.55),
        _det("button_white", conf=0.7),
    ]

    screen, info = classify_screen_unity_cup(dets)

    assert screen == "UnityCupRaceday"
    assert info == {"race_day": True}
