"""Offline/online HS-classification accuracy harness.

Measures the production image→HS pipeline's top-1 / top-3 accuracy over a manifest
of real products, against human-provided ground-truth HS6 codes.

The pipeline it exercises is the real one, service-for-service:

    product_vision.describe_product(db, product, llm)   # vision → AR/EN description
    hs_classifier.classify_product(db, product)         # name+description → HS6 cands

It runs IDENTICALLY offline and live — the ONLY difference is the LLM adapter the
registry returns:

  * no ``ANTHROPIC_API_KEY`` → the deterministic mock stands in, so the harness
    measures the engine's name-based resolver (``generated_offline = True``);
  * ``ANTHROPIC_API_KEY`` set → the real Anthropic vision adapter runs, so the
    harness measures true vision→HS. Same command, same code — no edits to go live.

This is a READ-ONLY measurement tool. Every product it creates lives inside one DB
transaction that is ALWAYS rolled back, so no evaluation rows survive. It never
fabricates a code (invariant I1): a pipeline that declares a gap is recorded as
``gap=True``, not invented.

CLI::

    python -m app.evals.hs_accuracy --manifest <path.json> \
        [--images-dir <dir>] [--out <report.json>] [--limit N]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session


def load_manifest(path: str | Path) -> list[dict[str, Any]]:
    """Parse the manifest JSON file into a list of product entries."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("manifest must be a JSON list of product objects")
    return data


def _resolve_image_url(image: str | None, images_dir: Path) -> str | None:
    """Turn a manifest ``image`` field into an ``image_url`` the vision pass loads.

    ``http(s)://`` and ``file://`` URLs pass straight through. A relative or
    absolute filesystem path is resolved against ``images_dir`` and returned as a
    ``file://`` URL. ``None``/empty stays ``None`` → text-only vision.
    """
    if not image:
        return None
    if image.startswith(("http://", "https://", "file://")):
        return image
    path = Path(image)
    if not path.is_absolute():
        path = images_dir / path
    return f"file://{path.resolve()}"


def _display_name(entry: dict[str, Any]) -> str:
    return entry.get("name_en") or entry.get("name_ar") or str(entry.get("id") or "?")


def _score_entry(
    entry: dict[str, Any],
    candidates: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    """Build the per-product report row, scoring it against ``expected_hs6``.

    Only entries with a non-empty ``expected_hs6`` are scored; for the rest the
    hit fields are ``None`` and only the top-3 proposals are reported for human
    labeling. A gap (no candidate / ``classification_status == "failed"``) is
    recorded, never back-filled with an invented code (I1).
    """
    expected = str(entry.get("expected_hs6") or "").strip()
    top = candidates[:3]
    top1_code = top[0]["code"] if top else None
    top1_conf = top[0].get("confidence") if top else None
    gap = (not candidates) or status == "failed"

    if expected:
        codes3 = [c["code"] for c in top]
        hit1_hs6: bool | None = top1_code == expected
        hit3_hs6: bool | None = expected in codes3
        hit1_hs4: bool | None = bool(top1_code) and top1_code[:4] == expected[:4]
        hit1_hs2: bool | None = bool(top1_code) and top1_code[:2] == expected[:2]
    else:
        hit1_hs6 = hit3_hs6 = hit1_hs4 = hit1_hs2 = None

    return {
        "id": entry.get("id"),
        "name": _display_name(entry),
        "expected_hs6": expected or None,
        "proposed": [{"code": c["code"], "confidence": c.get("confidence")} for c in top],
        "hit1_hs6": hit1_hs6,
        "hit3_hs6": hit3_hs6,
        "hit1_hs4": hit1_hs4,
        "hit1_hs2": hit1_hs2,
        "top1_confidence": top1_conf,
        "gap": gap,
        "classification_status": status,
        "sector": entry.get("sector"),
        "notes": entry.get("notes"),
    }


def _aggregate(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate hit rates over the scored products (non-empty expected_hs6)."""
    scored = [p for p in products if p["expected_hs6"]]
    scored_count = len(scored)
    total = len(products)

    def frac(key: str) -> float:
        if not scored_count:
            return 0.0
        return sum(1 for p in scored if p[key]) / scored_count

    confidences = [p["top1_confidence"] for p in scored if p["top1_confidence"] is not None]
    mean_conf = sum(confidences) / len(confidences) if confidences else None
    gap_count = sum(1 for p in scored if p["gap"])

    return {
        "top1_hs6": frac("hit1_hs6"),
        "top3_hs6": frac("hit3_hs6"),
        "top1_hs4": frac("hit1_hs4"),
        "top1_hs2": frac("hit1_hs2"),
        "gap_rate": (gap_count / scored_count) if scored_count else 0.0,
        "mean_top1_confidence": mean_conf,
        "scored_count": scored_count,
        "unscored_count": total - scored_count,
        "total": total,
    }


def run_harness(
    db: Session,
    manifest: list[dict[str, Any]],
    *,
    images_dir: str | Path,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run the real image→HS pipeline over ``manifest`` and score the results.

    Creates one ephemeral eval ``Factory`` and a ``Product`` per manifest entry
    inside the given session, runs ``describe_product`` then ``classify_product``
    on each, scores the candidates against the human ground truth, and ALWAYS
    rolls the transaction back so nothing is persisted. Returns the report dict.

    The LLM adapter comes from the registry (mock offline, Anthropic when keyed) —
    the harness itself is identical in both modes; ``generated_offline`` records
    which one ran, detected via the provider name containing ``"mock"``.
    """
    # Imported here (not at module top) so the module stays importable without a
    # configured app/DB, and so the engine is pulled in only by the services that
    # already lazy-import it.
    from app.models import Factory, Product
    from app.providers.registry import get_llm_provider
    from app.services.hs_classifier import classify_product
    from app.services.product_vision import describe_product

    images_dir = Path(images_dir)
    entries = list(manifest)
    if limit is not None:
        entries = entries[:limit]

    llm = get_llm_provider()
    provider_name = getattr(llm, "name", "unknown")
    generated_offline = "mock" in provider_name.lower()

    products_report: list[dict[str, Any]] = []
    try:
        factory = Factory(name_ar="مصنع تقييم HS", name_en="HS Accuracy Eval Factory")
        db.add(factory)
        db.flush()

        for entry in entries:
            name_en = str(entry.get("name_en") or "").strip()
            name_ar = str(entry.get("name_ar") or "").strip()
            if not name_en and not name_ar:
                raise ValueError(
                    f"manifest entry {entry.get('id')!r}: at least one of "
                    "name_en / name_ar is required"
                )
            product = Product(
                factory_id=factory.id,
                name_en=name_en or name_ar,
                name_ar=name_ar or name_en,
                currency="USD",
                image_url=_resolve_image_url(entry.get("image"), images_dir),
            )
            db.add(product)
            db.flush()

            # The real production path: vision describes, then the resolver classifies.
            describe_product(db, product, llm)
            classify_product(db, product)

            candidates = product.hs_candidates or []
            products_report.append(
                _score_entry(entry, candidates, product.classification_status)
            )

        return {
            "generated_offline": generated_offline,
            "provider": provider_name,
            "aggregate": _aggregate(products_report),
            "products": products_report,
        }
    finally:
        # No persistence — this is a measurement tool, never an ingest path.
        db.rollback()


# --------------------------------------------------------------------------
# Human-readable rendering
# --------------------------------------------------------------------------


def _fmt_hit(value: bool | None) -> str:
    if value is None:
        return " - "
    return " Y " if value else " . "


def _render_report(report: dict[str, Any]) -> str:
    offline = report["generated_offline"]
    lines: list[str] = []
    lines.append("=" * 78)
    if offline:
        lines.append("HS ACCURACY HARNESS — MOCK RUN (offline)")
        lines.append(
            "Measures the engine's NAME-BASED resolver, NOT real vision "
            "(no ANTHROPIC_API_KEY)."
        )
    else:
        lines.append("HS ACCURACY HARNESS — LIVE RUN")
        lines.append("Measures real vision→HS via the Anthropic adapter.")
    lines.append(f"provider: {report['provider']}")
    lines.append("=" * 78)

    header = f"{'id':<10} {'expected':<9} {'top-3 proposed':<26} {'conf':>6} {'@1':^3} {'@3':^3}"
    lines.append(header)
    lines.append("-" * 78)
    for p in report["products"]:
        codes = ",".join(c["code"] for c in p["proposed"]) or "(gap)"
        conf = p["top1_confidence"]
        conf_s = f"{conf:.3f}" if isinstance(conf, (int, float)) else "  -  "
        expected = p["expected_hs6"] or "-"
        lines.append(
            f"{str(p['id']):<10} {expected:<9} {codes:<26.26} {conf_s:>6} "
            f"{_fmt_hit(p['hit1_hs6'])}{_fmt_hit(p['hit3_hs6'])}"
        )

    agg = report["aggregate"]
    lines.append("-" * 78)
    lines.append("AGGREGATE (over scored products only)")

    def pct(key: str) -> str:
        return f"{agg[key] * 100:5.1f}%"

    mean_conf = agg["mean_top1_confidence"]
    mean_conf_s = f"{mean_conf:.3f}" if mean_conf is not None else "n/a"
    lines.append(
        f"  top1_hs6={pct('top1_hs6')}  top3_hs6={pct('top3_hs6')}  "
        f"top1_hs4={pct('top1_hs4')}  top1_hs2={pct('top1_hs2')}"
    )
    lines.append(
        f"  gap_rate={pct('gap_rate')}  mean_top1_confidence={mean_conf_s}"
    )
    lines.append(
        f"  scored={agg['scored_count']}  unscored={agg['unscored_count']}  "
        f"total={agg['total']}"
    )
    lines.append("=" * 78)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        prog="python -m app.evals.hs_accuracy",
        description="Measure image→HS pipeline top-1/top-3 accuracy over a manifest.",
    )
    parser.add_argument("--manifest", required=True, help="Path to the manifest JSON file.")
    parser.add_argument(
        "--images-dir",
        default=None,
        help="Base dir for relative image paths (default: the manifest's own directory).",
    )
    parser.add_argument("--out", default=None, help="Write the JSON report to this path.")
    parser.add_argument(
        "--limit", type=int, default=None, help="Evaluate only the first N entries."
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    images_dir = Path(args.images_dir) if args.images_dir else manifest_path.parent
    manifest = load_manifest(manifest_path)

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        report = run_harness(db, manifest, images_dir=images_dir, limit=args.limit)
    finally:
        db.close()

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(_render_report(report))
    return report


if __name__ == "__main__":
    main()
