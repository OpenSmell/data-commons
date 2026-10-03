#!/usr/bin/env python3
"""
OpenSmell Data Commons — Submission Validator

Validates that contributed recordings match the FORMAT.md spec.
Run before submitting to the data commons.

Usage:
    python validate_submission.py <path_to_csv_or_directory>

Exit codes:
    0 = valid
    1 = invalid
    2 = partial (some files valid, some not)
"""

import json
import os
import sys
import csv
import statistics
from pathlib import Path
from typing import Dict, List, Tuple, Optional


REQUIRED_METADATA_FIELDS = ["substance", "device_id", "session_date"]
SENSOR_INFO_FIELDS = ["unit", "sensor_model", "circuit"]
VALID_UNITS = ["resistance_ohm", "voltage", "rs_r0", "adc", "temperature_celsius", "humidity_percent"]
MIN_ROWS = 10

# Cadence plausibility bounds. Sampling rate is a device constant alongside Vcc,
# R_L and R0: every temporal feature divides a sample count by it. The timestamp
# column carries no unit tag, so a column in milliseconds is indistinguishable
# from a rate 1000x too high -- the two cases must be separated by checking the
# implied rate against the declared one rather than by trusting either.
MIN_RATE_RATIO = 0.5
MAX_RATE_RATIO = 2.0
MIN_PLAUSIBLE_DURATION_S = 1.0
MAX_PLAUSIBLE_DURATION_S = 24 * 3600.0

# Phase events. Labels are not enumerated: an arbitrary label is legitimate, so
# these are advisory hints rather than a closed vocabulary. `exposure_a` /
# `exposure_b` / `gap` are the labels used by the A->B transition protocol
# (docs/transition-protocol-ab.md).
KNOWN_PHASE_LABELS = {"baseline", "exposure_a", "exposure_b", "gap", "recovery"}

# A boundary recorded between samples is unavoidably quantised. One sample period
# of slack is normal; anything beyond that means the event time was estimated
# rather than observed, which is worth surfacing.
MAX_BOUNDARY_SLACK_PERIODS = 1.0


def validate_csv(filepath: Path) -> Tuple[bool, List[str], List[str]]:
    """Validate a CSV recording file.

    Returns (valid, errors, infos). Errors reject the submission; infos are
    advisory observations that do not.
    """
    errors: List[str] = []
    infos: List[str] = []
    
    # Check filename format
    stem = filepath.stem
    parts = stem.split("_")
    if len(parts) < 3:
        errors.append(f"Filename '{stem}' doesn't match pattern: {{substance}}_{{device_id}}_{{session_date}}.csv")
    
    # Check CSV structure
    try:
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)

            # Sensor columns use the same detection as the data-commons Rust
            # crate (lib.rs): `sensor_` prefix, `MQ` (e.g. "MQ-135"), or a
            # `ch`-prefixed generic column ("ch0", "ch1", ...).
            sensor_cols = [h for h in header if h.startswith("sensor_") or h.startswith("MQ") or h.startswith("ch")]
            if not sensor_cols:
                errors.append("No sensor columns found (expected sensor_*, MQ*, or ch* prefixes)")
            
            # Check row count
            row_count = sum(1 for _ in reader)
            if row_count < MIN_ROWS:
                errors.append(f"Too few rows: {row_count} (minimum: {MIN_ROWS})")

            if "timestamp" in header:
                errors.extend(_check_timestamps(filepath, infos))

    except Exception as e:
        errors.append(f"CSV read error: {e}")

    return len(errors) == 0, errors, infos


def _check_timestamps(filepath: Path, infos: List[str]) -> List[str]:
    """Plausibility-check the time column and report the rate it implies."""
    errors: List[str] = []
    times: List[float] = []
    with open(filepath, "r") as tf:
        for row in csv.DictReader(tf):
            try:
                times.append(float(row["timestamp"]))
            except (TypeError, ValueError, KeyError):
                pass

    if len(times) < 2:
        return ["timestamp column has fewer than 2 parseable values"]

    gaps = [b - a for a, b in zip(times, times[1:])]
    positive = [g for g in gaps if g > 0]
    if len(positive) < len(gaps):
        errors.append(
            f"timestamp is not monotonically non-decreasing: "
            f"{len(gaps) - len(positive)} of {len(gaps)} steps are not positive"
        )

    duration = times[-1] - times[0]
    if duration < MIN_PLAUSIBLE_DURATION_S or duration > MAX_PLAUSIBLE_DURATION_S:
        errors.append(
            f"Implausible duration {duration:.3f}s over {len(times)} rows; expected between "
            f"{MIN_PLAUSIBLE_DURATION_S}s and {MAX_PLAUSIBLE_DURATION_S / 3600:.0f}h. "
            f"Check the timestamp unit."
        )

    if positive:
        median_gap = statistics.median(positive)
        infos.append(
            f"timestamp implies {1.0 / median_gap:.4g} Hz (median gap {median_gap:.6g}s); "
            f"declare sampling_rate_hz so the two can be checked against each other"
        )

    return errors


def _recording_duration_s(filepath: Path) -> Optional[float]:
    """Duration from the timestamp column, or None if it is not usable."""
    times: List[float] = []
    try:
        with open(filepath, "r") as tf:
            for row in csv.DictReader(tf):
                try:
                    times.append(float(row["timestamp"]))
                except (TypeError, ValueError, KeyError):
                    pass
    except Exception:
        return None
    if len(times) < 2:
        return None
    duration = times[-1] - times[0]
    if duration < MIN_PLAUSIBLE_DURATION_S or duration > MAX_PLAUSIBLE_DURATION_S:
        return None
    return duration


def _implied_rate(csv_infos: List[str]) -> Optional[float]:
    """Recover the Hz figure the timestamp check reported, if it did."""
    for info in csv_infos:
        if "implies" in info and "Hz" in info:
            try:
                return float(info.split("implies")[1].split("Hz")[0].strip())
            except ValueError:
                return None
    return None


def _check_events(
    events: object, csv_infos: List[str], duration_s: Optional[float]
) -> Tuple[List[str], List[str]]:
    """Validate an optional `events` list of phase boundaries.

    A recording with phase labels is strictly more useful than one without: a
    consumer who has to infer phase boundaries from the response is inferring
    them from the thing being measured. Events are therefore optional here, but
    present-and-broken is an error, because a mislabelled phase is worse than an
    absent one -- it produces confident wrong answers rather than an obvious gap.

    Returns (errors, infos).
    """
    errors: List[str] = []
    infos: List[str] = []

    if not isinstance(events, list):
        return [f"events must be a list, got {type(events).__name__}"], []

    if not events:
        infos.append("events is empty; no phase labels for this recording")
        return errors, infos

    boundaries: List[Tuple[int, int, str]] = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            errors.append(f"events[{i}] must be an object, got {type(ev).__name__}")
            continue

        label = ev.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"events[{i}] is missing a non-empty 'label'")
            continue

        start = ev.get("start_ms", ev.get("start_s"))
        if not isinstance(start, (int, float)) or isinstance(start, bool) or start < 0:
            errors.append(f"events[{i}] ('{label}') needs a non-negative start_ms, got {start!r}")
            continue

        # start_s is accepted as an unambiguous alternative to start_ms. The two
        # keys differ by a factor of 1000 and sit next to a timestamp column that
        # is in seconds, so mixing them up is easy and silent -- which is why the
        # unit cross-check below looks for exactly that factor.
        if "start_ms" in ev:
            start_ms = float(start)
        else:
            start_ms = float(start) * 1000.0

        end_raw = ev.get("end_ms", ev.get("end_s"))
        end_ms = None
        if end_raw is not None:
            if not isinstance(end_raw, (int, float)) or isinstance(end_raw, bool):
                errors.append(f"events[{i}] ('{label}') has a non-numeric end: {end_raw!r}")
                continue
            end_ms = float(end_raw) if "end_ms" in ev else float(end_raw) * 1000.0
            if end_ms < start_ms:
                errors.append(
                    f"events[{i}] ('{label}') ends at {end_ms:g}ms before it starts at "
                    f"{start_ms:g}ms"
                )
                continue

        boundaries.append((start_ms, end_ms if end_ms is not None else start_ms, label))

    boundaries.sort(key=lambda t: t[0])
    for (a_start, a_end, a_label), (b_start, _b_end, b_label) in zip(boundaries, boundaries[1:]):
        if a_end > b_start:
            errors.append(
                f"events overlap: '{a_label}' ends at {a_end:g}ms but '{b_label}' starts "
                f"at {b_start:g}ms"
            )

    labels = [b[2] for b in boundaries]
    unknown = sorted({lbl for lbl in labels if lbl not in KNOWN_PHASE_LABELS})
    if unknown:
        infos.append(
            f"non-standard phase label(s): {', '.join(unknown)} "
            f"(labels are free-form; the conventional set is "
            f"{', '.join(sorted(KNOWN_PHASE_LABELS))})"
        )

    if len(boundaries) < len(events):
        # Some events were dropped above; a summary count would misdescribe them.
        pass
    else:
        plural = "s" if len(labels) != 1 else ""
        standard = "" if unknown else ", all with standard labels"
        infos.append(f"{len(labels)} phase event{plural}{standard}")

    last_ms = max(b[1] for b in boundaries)

    if duration_s is None:
        infos.append(
            "no usable timestamp column; phase events cannot be aligned to samples, "
            "only read in wall-clock order"
        )
        return errors, infos

    # Unit cross-check. The CSV timestamp column is in seconds by spec; the event
    # keys say ms. A 1000x discrepancy in either direction means one of the two was
    # authored in the wrong unit, and the recording is then unusable for kinetics.
    ratio = (last_ms / 1000.0) / duration_s
    if 500.0 < ratio < 2000.0:
        errors.append(
            f"phase events run to {last_ms / 1000:g}s but the recording is only "
            f"{duration_s:g}s ({ratio:.4g}x). One of the two is in the wrong time unit "
            f"-- the timestamp column must be seconds and events must be ms."
        )
    elif last_ms > duration_s * 1000.0 + 1.0:
        errors.append(
            f"phase events run to {last_ms / 1000:g}s but the recording is only "
            f"{duration_s:g}s; events extend past the end of the data"
        )
    else:
        infos.append(f"phase events fit within the {duration_s:g}s recording")

    unlabelled_s = duration_s - last_ms / 1000.0
    if unlabelled_s > 0:
        if ratio < 0.01:
            # Not an error: labelling one stimulus window inside a long drift
            # recording is legitimate. But 1/1000 is exactly the factor between the
            # _ms keys and seconds, so name the likely cause rather than leaving a
            # contributor to wonder why their phases look tiny.
            infos.append(
                f"phase events cover only {last_ms / 1000:g}s of a {duration_s:g}s "
                f"recording. If these events are meant to span the recording, the "
                f"values look like seconds written under 'start_ms'/'end_ms' keys: "
                f"multiply them by 1000, or rename the keys to start_s/end_s."
            )
        else:
            infos.append(
                f"last {unlabelled_s:.4g}s of the recording carries no phase label; "
                f"label it 'recovery' or leave the last event open-ended"
            )

    rate = _implied_rate(csv_infos)
    if rate and rate > 0:
        period_ms = 1000.0 / rate
        slack_ms = MAX_BOUNDARY_SLACK_PERIODS * period_ms
        off_grid = [
            lbl
            for _s, _e, lbl in boundaries
            if abs((_s / period_ms) - round(_s / period_ms)) * period_ms > slack_ms
        ]
        if off_grid:
            infos.append(
                f"event boundaries not on a sample edge (more than one {period_ms:.4g}ms "
                f"period off): {', '.join(sorted(set(off_grid)))}; boundaries appear "
                f"estimated rather than observed"
            )
        else:
            infos.append(f"event boundaries align with the {period_ms:.4g}ms sample period")

    return errors, infos


def validate_metadata(filepath: Path) -> Tuple[bool, List[str], List[str]]:
    """Validate a metadata JSON file."""
    errors: List[str] = []
    infos: List[str] = []

    try:
        with open(filepath, 'r') as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"], []
    except Exception as e:
        return False, [f"Cannot read file: {e}"], []
    
    # Check required fields
    for field in REQUIRED_METADATA_FIELDS:
        if field not in meta:
            errors.append(f"Missing required field: {field}")
    
    # Validate substance (single word)
    if "substance" in meta:
        substance = meta["substance"]
        if not substance.replace("-", "").replace("_", "").isalnum():
            errors.append(f"Substance '{substance}' should be alphanumeric (hyphens allowed for spaces)")
    
    # Validate sensor info
    if "sensor_info" in meta:
        for sensor_id, info in meta["sensor_info"].items():
            if not isinstance(info, str):
                errors.append(f"sensor_info.{sensor_id} should be a string")
    
    # Validate sensor units
    if "sensor_units" in meta:
        for sensor_id, unit in meta["sensor_units"].items():
            if unit not in VALID_UNITS:
                errors.append(f"sensor_units.{sensor_id} = '{unit}' is not valid. Use one of: {VALID_UNITS}")
    
    # Validate sensor models
    if "sensor_models" in meta:
        for sensor_id, model in meta["sensor_models"].items():
            if not isinstance(model, str):
                errors.append(f"sensor_models.{sensor_id} should be a string")

    # Declared rate. Required for anything involving kinetics or drift; advisory
    # otherwise, because a static reading is still usable without one.
    if "sampling_rate_hz" in meta:
        rate = meta["sampling_rate_hz"]
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
            errors.append(f"sampling_rate_hz must be a positive number, got {rate!r}")
        else:
            infos.append(f"declared sampling_rate_hz = {rate:g} Hz")
    else:
        infos.append(
            "no sampling_rate_hz declared; time-domain features cannot be validated "
            "for this recording"
        )

    return len(errors) == 0, errors, infos


def validate_pair(csv_path: Path, json_path: Optional[Path]) -> Tuple[bool, List[str], List[str]]:
    """Validate a CSV+JSON pair."""
    errors: List[str] = []
    infos: List[str] = []

    # Validate CSV
    csv_valid, csv_errors, csv_infos = validate_csv(csv_path)
    errors.extend([f"CSV: {e}" for e in csv_errors])
    infos.extend([f"CSV: {i}" for i in csv_infos])
    
    # Check for companion JSON
    if json_path is None:
        json_path = csv_path.with_suffix(".json")
    
    if json_path.exists():
        json_valid, json_errors, json_infos = validate_metadata(json_path)
        errors.extend([f"JSON: {e}" for e in json_errors])
        infos.extend([f"JSON: {i}" for i in json_infos])

        # Cross-validate: substance in filename should match metadata
        filename_substance = csv_path.stem.split("_")[0]
        with open(json_path) as jf:
            meta_json = json.load(jf)
        if "substance" in meta_json and filename_substance != meta_json["substance"]:
            errors.append(f"Filename substance '{filename_substance}' != metadata substance '{meta_json['substance']}'")

        # Cross-check the declared rate against the rate the timestamps imply.
        # This is the only place a seconds-vs-milliseconds mix-up can be caught.
        rate = meta_json.get("sampling_rate_hz")
        if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0:
            for info in csv_infos:
                if "implies" in info and "Hz" in info:
                    try:
                        implied = float(info.split("implies")[1].split("Hz")[0].strip())
                    except ValueError:
                        continue
                    ratio = implied / float(rate)
                    if ratio < MIN_RATE_RATIO or ratio > MAX_RATE_RATIO:
                        errors.append(
                            f"Timestamps imply {implied:.4g} Hz but sampling_rate_hz says "
                            f"{rate:g} Hz (ratio {ratio:.4g}). Most likely the timestamp "
                            f"column is not in seconds."
                        )
                    else:
                        infos.append(
                            f"declared and implied rates agree within {ratio:.3g}x"
                        )

        # Phase events, if the contributor declared any. The recording duration
        # comes from the CSV timestamps, so this check needs both files.
        if "events" in meta_json:
            duration_s = _recording_duration_s(csv_path)
            ev_errors, ev_infos = _check_events(meta_json["events"], csv_infos, duration_s)
            errors.extend([f"JSON: {e}" for e in ev_errors])
            infos.extend([f"JSON: {i}" for i in ev_infos])
    else:
        errors.append(f"No companion JSON: {json_path.name}")

    return len(errors) == 0, errors, infos


def validate_directory(dirpath: Path) -> Tuple[int, int, List[str]]:
    """Validate all files in a directory."""
    all_errors = []
    valid_count = 0
    total_count = 0
    
    csv_files = list(dirpath.glob("*.csv"))
    
    for csv_path in sorted(csv_files):
        total_count += 1
        json_path = csv_path.with_suffix(".json")
        valid, errors, infos = validate_pair(csv_path, json_path if json_path.exists() else None)

        if valid:
            valid_count += 1
            print(f"  ✓ {csv_path.name}")
        else:
            print(f"  ✗ {csv_path.name}")
            for error in errors:
                print(f"    ERROR: {error}")
                all_errors.append(f"{csv_path.name}: {error}")
        for info in infos:
            print(f"    info: {info}")

    return valid_count, total_count, all_errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_submission.py <path_to_csv_or_directory>")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    
    if path.is_file():
        print(f"Validating: {path.name}")
        valid, errors, infos = validate_pair(path, None)
        for info in infos:
            print(f"  info: {info}")
        if valid:
            print("  ✓ Valid")
            sys.exit(0)
        else:
            for error in errors:
                print(f"  ✗ {error}")
            sys.exit(1)
    
    elif path.is_dir():
        print(f"Validating directory: {path}")
        valid, total, errors = validate_directory(path)
        print(f"\nResult: {valid}/{total} files valid")
        if errors:
            sys.exit(2 if valid > 0 else 1)
        else:
            sys.exit(0)
    
    else:
        print(f"Error: {path} is not a file or directory")
        sys.exit(1)


if __name__ == "__main__":
    main()
