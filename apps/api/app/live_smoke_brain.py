"""Live brain-path smoke: one REAL product through the full chain (Wave 3 item 9).

image/name → HS classification (live Claude) → world screening (live Comtrade
sync) → stage-2 top-5 → competitor snapshot (+ paid prices only when keyed and
explicitly deepened) → buyers → a RENDERED executive Word report as the
artifact. This is the one lane that proves the product's brain end to end with
real keys — everything else in the repo is hermetic.

Fail-closed like app.live_smoke: without BOTH ``ANTHROPIC_API_KEY`` and
``COMTRADE_API_KEY`` the run prints SKIP and exits 0 — no partial paid spend,
no fabricated artifact. The Smartlead/mailbox send paths are NEVER touched.
The human HS-confirmation gate (I2) is simulated by confirming the classifier's
TOP proposal — acceptable only here because this harness never contacts a
buyer; it exists to prove the chain, and the simulation is loudly labeled.

Per-stage wall-clock is printed for every stage — the symptom-B budget
(bounded stages, no opaque hangs) is part of what this lane proves.
"""

from __future__ import annotations

import json
import sys
import time

SKIP = "SKIP"
PASS = "PASS"
FAIL = "FAIL"

#: A realistic Saudi export product — the exact class of name the old CSV
#: resolver failed on (symptom A), so this doubles as its live regression.
PRODUCT_NAME_AR = "تمر سكري فاخر معبأ 1كجم"
PRODUCT_NAME_EN = "Premium Sukkari Dates 1kg"


def _stage(results: list[dict], name: str, started: float, status: str, detail: str) -> None:
    elapsed = round(time.monotonic() - started, 1)
    results.append({"stage": name, "status": status, "seconds": elapsed, "detail": detail})
    print(f"  {status:4}  {name:<22} {elapsed:>7.1f}s  {detail}", flush=True)


def run(out_path: str = "executive_smoke.docx") -> int:
    from app.config import get_settings

    settings = get_settings()
    if not (settings.anthropic_api_key and settings.comtrade_api_key):
        print("  SKIP  brain-path — requires ANTHROPIC_API_KEY and COMTRADE_API_KEY")
        return 0

    from app.db import SessionLocal
    from app.models import Factory, Product
    from app.services import engine, hs_classifier
    from app.services.report_view import build_executive_result
    from app.workers import tasks

    results: list[dict] = []
    db = SessionLocal()
    try:
        factory = Factory(name_ar="مصنع الدخان الحي", name_en="Live Smoke Factory")
        db.add(factory)
        db.flush()
        product = Product(
            factory_id=factory.id,
            name_ar=PRODUCT_NAME_AR,
            name_en=PRODUCT_NAME_EN,
            currency="USD",
        )
        db.add(product)
        db.commit()

        # 1 — HS classification through the live Claude classifier (symptom A).
        t = time.monotonic()
        candidates = hs_classifier.classify_product(db, product)
        db.commit()
        if not candidates:
            _stage(
                results,
                "hs_classification",
                t,
                FAIL,
                f"no candidates for {PRODUCT_NAME_EN!r} — symptom A regressed",
            )
            return 1
        top = candidates[0]
        _stage(
            results,
            "hs_classification",
            t,
            PASS,
            f"{len(candidates)} candidates; top {top['code']} "
            f"(conf={top['confidence']}, llm={top['used_llm']})",
        )

        # 2 — simulated human confirmation of the TOP proposal (loudly labeled).
        t = time.monotonic()
        hs_classifier.confirm_hs_code(db, product, top["code"], user_id=None)
        db.commit()
        _stage(
            results,
            "hs_confirm(simulated)",
            t,
            PASS,
            f"confirmed {product.hs_code} — smoke-only simulation of I2",
        )

        # 3 — live Comtrade coverage sync for this HS6 (etl path, bounded sockets).
        t = time.monotonic()
        sync = tasks.sync_world_trade.apply(args=[product.hs_code]).result
        if not sync.get("synced"):
            _stage(results, "world_trade_sync", t, FAIL, str(sync))
            return 1
        _stage(results, "world_trade_sync", t, PASS, str(sync))

        # 4 — Stage-1 world screening + Stage-2 engine-model re-rank (chains 3).
        t = time.monotonic()
        from app.models import Analysis

        analysis = Analysis(product_id=product.id, product_name=PRODUCT_NAME_EN, status="pending")
        db.add(analysis)
        db.commit()
        _ = tasks.run_world_ranking.apply(args=[str(analysis.id), product.hs_code]).result
        _ = tasks.run_stage2_enrich.apply(args=[str(analysis.id), product.hs_code]).result
        db.expire_all()
        analysis = db.get(Analysis, analysis.id)
        if analysis.status == "failed":
            _stage(results, "world_funnel", t, FAIL, analysis.failure_reason or "failed")
            return 1
        _stage(results, "world_funnel", t, PASS, f"status={analysis.status}")

        # 5 — buyers + competitor snapshot on the #1 market (free path; the paid
        # importer-intel/prices layers stay structurally out without deepen).
        t = time.monotonic()
        from sqlalchemy import select

        from app.models import CountryRanking
        from app.providers.countries import iso3_to_iso2

        top_rank = db.scalars(
            select(CountryRanking)
            .where(CountryRanking.analysis_id == analysis.id)
            .order_by(CountryRanking.rank)
        ).first()
        top_iso2 = iso3_to_iso2(top_rank.importer_iso3) if top_rank else None
        if top_iso2:
            _ = tasks.run_discovery.apply(args=[str(product.id), top_iso2, str(analysis.id)]).result
            _stage(results, "buyers+snapshot", t, PASS, f"market={top_iso2}")
        else:
            _stage(results, "buyers+snapshot", t, SKIP, "no iso2 for top market")

        # 5b — paid observed prices, ONLY with the key and an explicit deepen scope.
        if settings.localprice_api_key and top_iso2:
            t = time.monotonic()
            from app.services.observed_prices import fetch_prices_for_market

            with engine.deepen_scope(True):
                priced = fetch_prices_for_market(db, product, top_iso2)
            db.commit()
            _stage(results, "observed_prices", t, PASS, str(priced))
        else:
            print("  SKIP  observed_prices — no LOCALPRICE_API_KEY (paid layer closed)")

        # 6 — THE artifact: the executive multi-market Word report.
        t = time.monotonic()
        from silk_render import build_view
        from silk_reports import render_executive_docx

        result = build_executive_result(db, product)
        view = build_view(result)
        path = render_executive_docx(view, out_path)
        with open(path or out_path, "rb") as fh:
            blob = fh.read()
        if blob[:2] != b"PK" or len(blob) < 5000:
            _stage(results, "executive_report", t, FAIL, f"not a plausible docx ({len(blob)}B)")
            return 1
        exec_markets = len((result.get("executive") or {}).get("markets") or [])
        _stage(
            results,
            "executive_report",
            t,
            PASS,
            f"{len(blob)}B docx at {out_path}; exec markets={exec_markets}",
        )

        total = round(sum(r["seconds"] for r in results), 1)
        print(f"\n  brain path complete in {total}s — artifact: {out_path}")
        print(json.dumps(results, ensure_ascii=False))
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = argv[argv.index("--out") + 1] if "--out" in argv else "executive_smoke.docx"
    return run(out)


if __name__ == "__main__":
    raise SystemExit(main())
