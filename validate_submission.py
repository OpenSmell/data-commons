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
