"""مدخل العامل المُجدول — scheduled worker entrypoint (M2).

Usage:  python3 tools/refresh.py     (Railway cron / docker-compose worker)
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_collectors  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(silk_collectors.refresh(), ensure_ascii=False))
