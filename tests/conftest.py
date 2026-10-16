"""Shared test fixtures for the submission validator.

The validator is a standalone script rather than a package member, so it is
imported by path -- the same way a contributor runs it.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import validate_submission as vs