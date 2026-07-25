import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fit4garmin.app import app  # noqa: E402, F401
