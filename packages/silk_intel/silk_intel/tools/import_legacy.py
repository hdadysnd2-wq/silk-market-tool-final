"""استيراد الإرث — import legacy silk.db analyses into the unified store (M1).

يقرأ analyses/market_scores/outcome من silk_storage القديم ويعيد حفظها في
silk_store الموحّد مع `legacy_id` للتتبّع. آمن الإعادة (idempotent): تحليل قديم
سبق استيراده (نفس legacy_id) يُتجاوز. لا يحذف القديم إطلاقاً (قرار المالك).

Usage:  python3 tools/import_legacy.py [old_silk_db_path]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import silk_storage  # noqa: E402 — legacy source (read-only here)
import silk_store    # noqa: E402 — unified destination


def import_legacy(old_path: str | None = None) -> dict:
    """رحّل كل التحليلات القديمة — returns {imported, skipped, outcomes}."""
    silk_store.migrate()
    with silk_store.connect() as conn:
        done = {r[0] for r in conn.execute(
            "SELECT legacy_id FROM analyses WHERE legacy_id IS NOT NULL").fetchall()}
    imported = skipped = outcomes = 0
    for meta in silk_storage.list_analyses(path=old_path):
        lid = meta["id"]
        if lid in done:
            skipped += 1
            continue
        full = silk_storage.get_analysis(lid, path=old_path)
        if not full:
            continue
        result = full.get("result") if isinstance(full, dict) else None
        if result is None:  # بعض الإصدارات تعيد الحمولة مباشرة
            result = full if isinstance(full, dict) else {}
        new_id = silk_store.save_analysis(result, legacy_id=lid)
        out = meta.get("outcome")
        if out:
            silk_store.set_outcome(new_id, out,
                                   note=f"مستورد من silk.db القديم (id={lid})")
            outcomes += 1
        imported += 1
    return {"imported": imported, "skipped": skipped, "outcomes": outcomes}


if __name__ == "__main__":
    old = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(import_legacy(old), ensure_ascii=False))
