"""The Factory Report Journey, end to end, driven through the service layer.

The flagship journey the product exists for, for ONE seeded product, printed
step by step so it is reviewable from a terminal without the frontend:

    intake + confirmed HS  →  screen the world (Stage 1, top-20% cut)
    →  transparent 7-component re-rank (Stage 2)  →  Top 5 with a rationale line
    →  observed competitor prices per market  →  a verified buyer list per market
    →  render the downloadable executive report  →  note the deep-research report.

    python -m app.seeds.demo_factory_report_journey

Runs on the offline demo seed with zero keys: the market screen uses the seeded
world_trade rows, prices/enrichment/shipments come from the deterministic
sample providers in ``local`` (labeled as such), and the report renders to the
configured storage. With real keys + COMTRADE_API_KEY the SAME code path runs
against live data — nothing here is journey-only scaffolding.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import Analysis, CountryRanking, Factory, Product
from app.services import engine
from app.services.api_budget import budget_scope
from app.services.buyer_discovery import buyers_for_product, discover_buyers
from app.services.observed_prices import fetch_prices_for_market
from app.services.ranking import rank_and_persist
from app.services.ranking_rationale import build_rationale
from app.services.report_view import build_executive_result
from app.services.stage2 import enrich_shortlist


def _hr(title: str) -> None:
    print(f"\n{'─' * 70}\n{title}\n{'─' * 70}")


def _iso3_to_iso2(iso3: str) -> str:
    from app.providers.countries import iso3_to_iso2

    return iso3_to_iso2(iso3) or iso3[:2]


def run() -> None:
    with session_scope() as db:
        factory = db.scalar(select(Factory).where(Factory.name_en == "Jeddah Poly Industries"))
        product = db.scalar(select(Product).where(Product.factory_id == factory.id))
        if product is None or not product.hs_code:
            raise SystemExit("Seed first: make seed (need a confirmed-HS demo product).")

        _hr("1. PRODUCT INTAKE (seeded)")
        print(f"Factory : {factory.name_en} — {factory.city}")
        print(f"Product : {product.name_en} / {product.name_ar}")
        print(f"HS code : {product.hs_code}  (confirmed={product.hs_confirmed_by_user})")

        # -- Stage 1: screen every covered market, keep the top-20% shortlist ---
        _hr("2. WORLD SCREEN — Stage 1 (top-20% cut)")
        analysis = Analysis(
            product_id=product.id, product_name=product.name_en, status="classified"
        )
        db.add(analysis)
        db.flush()
        rank_and_persist(db, analysis, product.hs_code)
        db.flush()
        print(
            f"Screened {analysis.total_screened} covered markets → kept "
            f"{analysis.shortlisted} (top-20%, clamped [5,30])."
        )

        # -- Stage 2: transparent 7-component re-rank of the shortlist ----------
        _hr("3. TRANSPARENT RE-RANK — Stage 2 (7 components, each with its source)")
        with engine.deepen_scope(True), budget_scope(label=f"journey:{analysis.id}"):
            enrich_shortlist(db, analysis, product.hs_code)
        db.flush()

        top5 = db.scalars(
            select(CountryRanking)
            .where(CountryRanking.analysis_id == analysis.id)
            .order_by(CountryRanking.rank)
            .limit(5)
        ).all()

        _hr("4. TOP 5 MARKETS — with a one-line justification each")
        for r in top5:
            rationale = build_rationale((r.enrichment or {}).get("score_components"))
            line = rationale["en"] if rationale else "Ranked on screened import volume."
            score = r.stage2_score if r.stage2_score is not None else r.screen_score
            hub = " [transit hub — penalized]" if r.is_transit_hub else ""
            print(f"  #{r.rank}  {r.importer_iso3}  score={float(score):.3f}{hub}")
            print(f"        {line}")

        # -- Observed prices per market (real source or declared gap) ----------
        _hr("5. OBSERVED COMPETITOR PRICES — per Top-5 market")
        from app.models import MarketSnapshot

        for r in top5:
            iso2 = _iso3_to_iso2(r.importer_iso3)
            with engine.deepen_scope(True), budget_scope(label=f"prices:{analysis.id}:{iso2}"):
                priced = fetch_prices_for_market(db, product, iso2)
            if not priced.get("count"):
                print(f"  {r.importer_iso3}: pricing pending data source (no price provider).")
                continue
            snap = db.scalar(
                select(MarketSnapshot).where(
                    MarketSnapshot.hs_code == product.hs_code,
                    MarketSnapshot.market_iso2 == iso2,
                )
            )
            rows = (snap.observed_prices if snap else None) or []
            src = rows[0].get("source") if rows else "?"
            label = " (SAMPLE)" if "mock" in str(src) or "sample" in str(src) else ""
            print(
                f"  {r.importer_iso3}: {priced['count']} observed listing(s), source={src}{label}"
            )
            for p in rows[:2]:
                print(
                    f"       {p.get('competitor', '?')}: "
                    f"{p.get('price', '?')} {p.get('currency', '')}  {p.get('url', '')}"
                )

        # -- Buyer list per market (SAMPLE-labeled offline) --------------------
        _hr("6. PROSPECTIVE BUYER LIST — per Top-5 market")
        for r in top5[:3]:  # first three markets for a readable demo
            iso2 = _iso3_to_iso2(r.importer_iso3)
            with budget_scope(label=f"discovery:{analysis.id}:{iso2}"):
                summary = discover_buyers(db, product, iso2, analysis_id=analysis.id)
            db.flush()
            pairs = buyers_for_product(db, product.id, iso2)[:3]
            print(f"  {r.importer_iso3}: discovered {summary.get('discovered', 0)} companies")
            for match, buyer in pairs:
                print(f"       [{match.relevance_score:>3}] {buyer.name} ({buyer.country_iso2})")

        # -- The downloadable executive report --------------------------------
        _hr("7. EXECUTIVE REPORT — the downloadable deliverable")
        result = build_executive_result(db, product)
        markets = result["executive"]["markets"]
        print(f"Executive result: {len(markets)} market block(s), rendered to Word.")
        from pathlib import Path
        from tempfile import mkdtemp

        from silk_render import build_view
        from silk_reports import render_executive_docx

        out = render_executive_docx(build_view(result), str(Path(mkdtemp()) / "exec.docx"))
        size = Path(out).stat().st_size
        print(f"Rendered {size:,} bytes of .docx (prices + buyers sections included).")

        # -- Deep research (Top 5) — gated, additive -------------------------
        _hr("8. DEEP RESEARCH REPORT (Top 5) — opt-in, key-gated")
        allowed = engine.deep_research_allowed()
        if allowed:
            print("ANTHROPIC_API_KEY present — the deep-research report can run (paid).")
        else:
            print(
                "Not configured: the deep-research report is fail-closed and renders a "
                "'pending API key' declared gap (never fabricated). Set ANTHROPIC_API_KEY "
                "to enable it (see docs/LAUNCH_KEYS.md)."
            )

        print(
            "\n✓ Factory Report Journey complete — intake → world screen → Top 5 "
            "→ report with prices + buyers, all from real journey code."
        )


if __name__ == "__main__":
    run()
