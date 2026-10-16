"""Validator behaviour for phase events.

Phase events are optional in a submission, but a *present and broken* phase
boundary is rejected: a mislabelled phase yields confident wrong kinetics rather
than an obvious gap. These tests pin the cases that distinction turns on --
in particular that a ~1000x unit mismatch is rejected in **both** directions,
which is what FORMAT.md and the A->B transition protocol both claim.
"""

import json

import pytest

import validate_submission as vs


def csv_infos(rate_hz=2.0):
    """The info line `_check_timestamps` emits, so `_implied_rate` can read it."""
    return [
        f"timestamp implies {rate_hz:.4g} Hz (median gap {1000.0 / rate_hz:.6g}s); "
        f"declare sampling_rate_hz so the two can be checked against each other"
    ]


def check(events, duration_s, rate_hz=2.0):
    return vs._check_events(events, csv_infos(rate_hz), duration_s)


# The A->B transition protocol's five phases, in FORMAT.md's example.
AB_EVENTS = [
    {"label": "baseline", "start_ms": 0, "end_ms": 300000},
    {"label": "exposure_a", "start_ms": 300000, "end_ms": 360000},
    {"label": "gap", "start_ms": 360000, "end_ms": 960000},
    {"label": "exposure_b", "start_ms": 960000, "end_ms": 1020000},
    {"label": "recovery", "start_ms": 1020000},
]


# ---------------------------------------------------------------- the wire labels

def test_event_labels_from_the_wire_protocol_are_conventional():
    """`EVENT` uses baseline/exposure/recovery; they must not be flagged."""
    errors, infos = check(
        [
            {"label": "baseline", "start_ms": 0, "end_ms": 300000},
            {"label": "exposure", "start_ms": 300000, "end_ms": 360000},
            {"label": "recovery", "start_ms": 360000},
        ],
        duration_s=400.0,
    )
    assert errors == []
    assert not any("non-standard" in i for i in infos)


def test_non_conventional_label_is_informational():
    errors, infos = check([{"label": "flush", "start_ms": 0}], duration_s=10.0)
    assert errors == []
    assert any("non-standard phase label(s): flush" in i for i in infos)


# ---------------------------------------------------------------- the unit mismatch

def test_events_1000x_too_long_are_rejected():
    errors, _ = check([{"label": "baseline", "start_ms": 100_000_000}], duration_s=100.0)
    assert len(errors) == 1
    assert "wrong time unit" in errors[0]


def test_events_1000x_too_short_are_rejected():
    """The mirror-image mistake: seconds written under `start_ms` keys.

    This is the direction that used to be reported as information only, which
    contradicted FORMAT.md ("flags ... in either direction") and the transition
    protocol ("rejects ... a ~1000x unit mismatch").
    """
    errors, infos = check([{"label": "baseline", "start_ms": 100}], duration_s=100.0)
    assert len(errors) == 1
    assert "1000x too short" in errors[0]
    assert "start_s/end_s" in errors[0]
    # The misleading "no phase label" note must not accompany a unit error.
    assert not any("carries no phase label" in i for i in infos)


def test_millisecond_timestamp_column_is_rejected_as_a_rate_mismatch():
    """Same mistake seen from the other side: timestamps in ms, events in ms."""
    errors, _ = vs._check_events([{"label": "baseline", "start_ms": 0}], csv_infos(), 1.0)
    assert errors == []
    # duration 1000x too small -> events look 1000x too long, which is the
    # overshoot window and already an error.
    errors, _ = check([{"label": "baseline", "start_ms": 0, "end_ms": 100_000}], duration_s=0.1)
    assert len(errors) == 1
    assert "wrong time unit" in errors[0]


def test_partial_coverage_is_not_a_unit_error():
    """Labelling part of a long recording is legitimate, not a unit mistake."""
    errors, infos = check(
        [{"label": "exposure", "start_ms": 5000, "end_ms": 60000}], duration_s=100.0
    )
    assert errors == []
    assert any("phase events fit within" in i for i in infos)
    assert any("last 40s" in i for i in infos)


# ---------------------------------------------------------------- structure

def test_overlap_is_rejected():
    errors, _ = check(
        [
            {"label": "baseline", "start_ms": 0, "end_ms": 5000},
            {"label": "exposure", "start_ms": 4000, "end_ms": 9000},
        ],
        duration_s=10.0,
    )
    assert any("events overlap" in e for e in errors)


def test_inverted_interval_is_rejected():
    errors, _ = check([{"label": "exposure", "start_ms": 9000, "end_ms": 4000}], duration_s=10.0)
    assert any("before it starts" in e for e in errors)


def test_seconds_keys_match_millisecond_keys():
    errors_ms, _ = check(AB_EVENTS, duration_s=1200.0)
    errors_s, _ = check(
        [
            {"label": "baseline", "start_s": 0, "end_s": 300},
            {"label": "exposure_a", "start_s": 300, "end_s": 360},
            {"label": "gap", "start_s": 360, "end_s": 960},
            {"label": "exposure_b", "start_s": 960, "end_s": 1020},
            {"label": "recovery", "start_s": 1020},
        ],
        duration_s=1200.0,
    )
    assert errors_ms == []
    assert errors_s == []


def test_whole_transition_recording_validates():
    errors, infos = check(AB_EVENTS, duration_s=1200.0)
    assert errors == []
    assert any("5 phase events, all with standard labels" in i for i in infos)
    assert any("align with the 500ms sample period" in i for i in infos)


def test_off_grid_boundary_is_informational():
    # 6200 ms at 2 Hz is 200 ms from the nearest 500 ms edge: past the slack.
    errors, infos = check([{"label": "exposure", "start_ms": 6200}], duration_s=20.0)
    assert errors == []
    assert any("not on a sample edge" in i for i in infos)


def test_boundary_within_the_slack_counts_as_aligned():
    """100 ms off at 2 Hz is inside a quarter-period of slack."""
    errors, infos = check([{"label": "exposure", "start_ms": 6100}], duration_s=20.0)
    assert errors == []
    assert any("align with the 500ms sample period" in i for i in infos)


@pytest.mark.parametrize(
    "events",
    [
        "baseline",
        [42],
        [{}],
        [{"label": "", "start_ms": 0}],
        [{"label": "baseline", "start_ms": -1}],
        [{"label": "baseline", "start_ms": "soon"}],
        [{"label": "baseline", "start_ms": 0, "end_ms": "later"}],
    ],
)
def test_malformed_events_are_rejected(events):
    errors, _ = check(events, duration_s=10.0)
    assert errors


def test_null_end_is_the_open_ended_final_phase():
    """`"end_ms": null` is how SessionEvent serialises an absent end; not an error."""
    errors, _ = check([{"label": "recovery", "start_ms": 0, "end_ms": None}], duration_s=10.0)
    assert errors == []


def test_empty_events_is_informational():
    errors, infos = check([], duration_s=10.0)
    assert errors == []
    assert any("events is empty" in i for i in infos)


# ---------------------------------------------------------------- end to end

def write_submission(tmp_path, events, n_rows=400, rate_hz=2.0):
    csv_path = tmp_path / "ethanol_esp32-001_20260115.csv"
    lines = ["timestamp,ch0,ch1"]
    for i in range(n_rows):
        lines.append(f"{i / rate_hz:.6f},{1000 + i},{2000 + i}")
    csv_path.write_text("\n".join(lines) + "\n")

    meta = {
        "substance": "ethanol",
        "device_id": "esp32-001",
        "session_date": "2026-01-15",
        "sensor_units": {"ch0": "adc", "ch1": "adc"},
        "sensor_models": {"ch0": "MQ-135", "ch1": "MQ-3"},
        "sampling_rate_hz": rate_hz,
        "events": events,
    }
    json_path = csv_path.with_suffix(".json")
    json_path.write_text(json.dumps(meta))
    return csv_path, json_path


def test_event_annotated_recording_validates_end_to_end(tmp_path):
    csv_path, json_path = write_submission(
        tmp_path,
        [
            {"label": "baseline", "start_ms": 0, "end_ms": 100000},
            {"label": "exposure", "start_ms": 100000, "end_ms": 160000},
            {"label": "recovery", "start_ms": 160000},
        ],
    )
    valid, errors, _ = vs.validate_pair(csv_path, json_path)
    assert errors == []
    assert valid


def test_under_scaled_events_fail_end_to_end(tmp_path):
    # A ~200 s recording whose only event spans 0.2 s: seconds written under
    # `start_ms`/`end_ms` keys.
    csv_path, json_path = write_submission(
        tmp_path, [{"label": "baseline", "start_ms": 0, "end_ms": 200}]
    )
    valid, errors, _ = vs.validate_pair(csv_path, json_path)
    assert not valid
    assert any("1000x too short" in e for e in errors)