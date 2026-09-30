#!/usr/bin/env python3
"""Пересобрать web/assets/oko-data.js из data/*.json."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from okolib.webdata import build  # noqa: E402

if __name__ == "__main__":
    print(build(ROOT))
