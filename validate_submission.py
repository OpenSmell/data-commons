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
from pathlib import Path
from typing import Dict, List, Tuple, Optional


REQUIRED_METADATA_FIELDS = ["substance", "device_id", "session_date"]
SENSOR_INFO_FIELDS = ["unit", "sensor_model", "circuit"]
VALID_UNITS = ["resistance_ohm", "voltage", "rs_r0", "adc", "temperature_celsius", "humidity_percent"]
MIN_ROWS = 10


def validate_csv(filepath: Path) -> Tuple[bool, List[str]]:
    """Validate a CSV recording file."""
    errors = []
    
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
                
    except Exception as e:
        errors.append(f"CSV read error: {e}")
    
    return len(errors) == 0, errors


def validate_metadata(filepath: Path) -> Tuple[bool, List[str]]:
    """Validate a metadata JSON file."""
    errors = []
    
    try:
        with open(filepath, 'r') as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]
    except Exception as e:
        return False, [f"Cannot read file: {e}"]
    
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
    
    return len(errors) == 0, errors


def validate_pair(csv_path: Path, json_path: Optional[Path]) -> Tuple[bool, List[str]]:
    """Validate a CSV+JSON pair."""
    errors = []
    
    # Validate CSV
    csv_valid, csv_errors = validate_csv(csv_path)
    errors.extend([f"CSV: {e}" for e in csv_errors])
    
    # Check for companion JSON
    if json_path is None:
        json_path = csv_path.with_suffix(".json")
    
    if json_path.exists():
        json_valid, json_errors = validate_metadata(json_path)
        errors.extend([f"JSON: {e}" for e in json_errors])

        # Cross-validate: substance in filename should match metadata
        filename_substance = csv_path.stem.split("_")[0]
        with open(json_path) as jf:
            meta_json = json.load(jf)
        if "substance" in meta_json and filename_substance != meta_json["substance"]:
            errors.append(f"Filename substance '{filename_substance}' != metadata substance '{meta_json['substance']}'")
    else:
        errors.append(f"No companion JSON: {json_path.name}")
    
    return len(errors) == 0, errors


def validate_directory(dirpath: Path) -> Tuple[int, int, List[str]]:
    """Validate all files in a directory."""
    all_errors = []
    valid_count = 0
    total_count = 0
    
    csv_files = list(dirpath.glob("*.csv"))
    
    for csv_path in sorted(csv_files):
        total_count += 1
        json_path = csv_path.with_suffix(".json")
        valid, errors = validate_pair(csv_path, json_path if json_path.exists() else None)
        
        if valid:
            valid_count += 1
            print(f"  ✓ {csv_path.name}")
        else:
            print(f"  ✗ {csv_path.name}")
            for error in errors:
                print(f"    {error}")
                all_errors.append(f"{csv_path.name}: {error}")
    
    return valid_count, total_count, all_errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_submission.py <path_to_csv_or_directory>")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    
    if path.is_file():
        print(f"Validating: {path.name}")
        valid, errors = validate_pair(path, None)
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
