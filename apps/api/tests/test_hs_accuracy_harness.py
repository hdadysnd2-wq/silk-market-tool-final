"""Offline structural test for the HS-accuracy harness.

Runs the harness end to end against the shipped sample manifest with the default
(mock) LLM provider — no network. It asserts the report's *shape*, not any
particular accuracy number: the mock resolver's score is not the point, that it
runs the real pipeline and reports correctly is.
"""

from __future__ import annotations

from pathlib import Path

from app.evals.hs_accuracy import load_manifest, run_harness

SAMPLE_MANIFEST = Path(__file__).resolve().parents[1] / "app" / "evals" / "sample_manifest.json"

_AGGREGATE_KEYS = {
    "top1_hs6",
    "top3_hs6",
    "top1_hs4",
    "top1_hs2",
    "gap_rate",
    "mean_top1_confidence",
    "scored_count",
    "unscored_count",
    "total",
}
_FRACTION_KEYS = {"top1_hs6", "top3_hs6", "top1_hs4", "top1_hs2", "gap_rate"}


def test_harness_runs_offline_and_reports_structure(db):
    manifest = load_manifest(SAMPLE_MANIFEST)
    report = run_harness(db, manifest, images_dir=SAMPLE_MANIFEST.parent)

    # Offline: the registry returns the mock, so this measures the name resolver.
    assert report["generated_offline"] is True
    assert "mock" in report["provider"].lower()

    # One products row per manifest entry.
    assert len(report["products"]) == len(manifest)

    agg = report["aggregate"]
    assert set(agg) == _AGGREGATE_KEYS
    assert agg["total"] == len(manifest)
    assert agg["scored_count"] + agg["unscored_count"] == agg["total"]

    # Scored fractions are well-formed probabilities.
    for key in _FRACTION_KEYS:
        assert 0.0 <= agg[key] <= 1.0

    # Every product row carries the scoring + reporting fields.
    for product in report["products"]:
        assert {
            "id",
            "name",
            "expected_hs6",
            "proposed",
            "hit1_hs6",
            "hit3_hs6",
            "hit1_hs4",
            "hit1_hs2",
            "top1_confidence",
            "gap",
            "classification_status",
            "sector",
            "notes",
        } <= set(product)
        assert isinstance(product["proposed"], list)


def test_harness_rolls_back_and_persists_nothing(db):
    """The harness must leave no Factory / Product rows behind."""
    from app.models import Factory, Product

    manifest = load_manifest(SAMPLE_MANIFEST)
    run_harness(db, manifest, images_dir=SAMPLE_MANIFEST.parent)

    # The harness rolled its own transaction back; the session sees no eval rows.
    assert db.query(Product).count() == 0
    assert db.query(Factory).count() == 0


def test_limit_caps_the_number_of_products(db):
    manifest = load_manifest(SAMPLE_MANIFEST)
    report = run_harness(db, manifest, images_dir=SAMPLE_MANIFEST.parent, limit=2)
    assert report["aggregate"]["total"] == 2
    assert len(report["products"]) == 2
