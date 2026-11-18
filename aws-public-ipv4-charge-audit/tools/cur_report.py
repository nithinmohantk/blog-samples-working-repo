"""Price last month's public IPv4 usage from a CUR CSV at the February 2024 rate.

    python tools/cur_report.py s3-download/my-cur-00001.csv.gz
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipv4_audit.cur_summary import summarise_cur  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: cur_report.py <cur file .csv or .csv.gz>")
    print(json.dumps(summarise_cur(sys.argv[1]), indent=2))
