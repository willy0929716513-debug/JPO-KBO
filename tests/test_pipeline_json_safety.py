"""Regression test for a real bug: a NaN float anywhere in the pipeline
payload made json.dump write a bare `NaN` token (valid to Python's json
module, invalid per the JSON spec), which every browser's JSON.parse
rejects outright -- silently breaking the whole dashboard with no error on
the Python side that produced the file. See src/pipeline/daily_run.py's
_json_safe().
"""
import json
import math

from src.pipeline.daily_run import _json_safe


def test_json_safe_replaces_nan_and_inf_with_none():
    payload = {
        "a": float("nan"),
        "b": float("inf"),
        "c": -float("inf"),
        "d": 1.5,
        "e": None,
        "nested": {"x": float("nan"), "y": [1, float("nan"), 3]},
        "list": [float("nan"), 2.0],
    }
    cleaned = _json_safe(payload)

    assert cleaned["a"] is None
    assert cleaned["b"] is None
    assert cleaned["c"] is None
    assert cleaned["d"] == 1.5
    assert cleaned["e"] is None
    assert cleaned["nested"]["x"] is None
    assert cleaned["nested"]["y"] == [1, None, 3]
    assert cleaned["list"] == [None, 2.0]


def test_json_safe_output_is_strictly_valid_json():
    payload = {"price": float("nan"), "values": [1.0, float("inf"), 3.0]}
    cleaned = _json_safe(payload)

    # allow_nan=False makes this raise ValueError if any NaN/Infinity survived cleaning
    serialized = json.dumps(cleaned, allow_nan=False)
    round_tripped = json.loads(serialized)  # a strict JSON parser accepts it (unlike the raw NaN token)

    assert round_tripped["price"] is None
    assert round_tripped["values"] == [1.0, None, 3.0]


def test_json_safe_leaves_normal_values_untouched():
    payload = {"symbol": "AAPL", "price": 123.45, "count": 3, "flag": True, "items": ["a", "b"]}
    assert _json_safe(payload) == payload
