"""Product → HS6 classification via the engine's general classifier.

The platform keeps NO parallel HS logic: every proposal comes from the engine's
``classify_general`` through :func:`app.services.engine.classify_hs_general`
(one classifier only — Wave 3, symptom A). Internally the engine runs its
deterministic seed analyzer first and escalates to Claude over the FULL WCO
nomenclature only when that cannot decide, with spend reserved atomically
against the daily cap and results cached — so the offline CSV path survives as
the engine's own explicit fallback, and its use is visible in each candidate's
``provider``/``used_llm`` provenance. This service only shapes the result into
``product.hs_candidates`` and lazily backfills the HS catalogue so a proposed
code stays foreign-key-valid and confirmable.

Commit rules (I2 as amended by owner decisions 2026-08-08, ADR-0009 +
ADR-0010): ``hs_confirmed_by_user`` is set solely in :func:`confirm_hs_code` —
human action only, and a human confirm/override always wins. Additionally,
when the engine returns ``tier="auto"`` — its STRICT seed-anchored verdict
(verified top candidate, overlap ≥ 0.8, clear margin) or its LLM-decisive
verdict (``source="llm_decisive"``: the consulted model explicitly declared
decisiveness, cleared the confidence + margin bar, and survived the structural
gate — ADR-0010) — :func:`classify_product` commits ``product.hs_code`` tagged
``hs_auto_classified=True``, and never overwrites a human-confirmed code.
A ``tier="manual"`` result is a declared gap — status ``failed`` with NO
invented candidates (invariant I1); the UI's search + manual-entry fallback
remains the last resort.
"""

from __future__ import annotations

import csv
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import HSCode, HSCorrection, Product

log = get_logger(__name__)

#: Lazily-parsed ``{hs_code: row}`` view of the engine's HS seed CSV, used to
#: backfill the platform catalogue on demand (see :func:`ensure_hs_code`). Parsed
#: once on first use and cached for the process lifetime.
_ENGINE_HS_ROWS: dict[str, dict[str, str]] | None = None


def _engine_hs_rows() -> dict[str, dict[str, str]]:
    """Parse (once) the engine's HS seed CSV into a ``{code: row}`` lookup.

    The CSV is located relative to the resolver module so the two never drift.
    A missing/unreadable seed degrades to an empty map (a declared gap, not a
    crash) — ``ensure_hs_code`` then simply cannot backfill.
    """
    global _ENGINE_HS_ROWS
    if _ENGINE_HS_ROWS is None:
        import silk_hs_resolver

        csv_path = Path(silk_hs_resolver.__file__).parent / "data" / "hs_codes.csv"
        rows: dict[str, dict[str, str]] = {}
        try:
            with csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    code = (row.get("hs_code") or "").strip()
                    if code:
                        rows[code] = row
        except OSError as exc:  # missing/unreadable seed → empty (declared gap)
            log.warning("hs_seed_csv_unreadable", path=str(csv_path), error=str(exc))
        _ENGINE_HS_ROWS = rows
    return _ENGINE_HS_ROWS


def ensure_hs_code(db: Session, code: str) -> HSCode | None:
    """Return the catalogue row for ``code``, backfilling it from the engine seed.

    The engine resolver proposes real international HS6 codes that may not be in
    the platform's curated ``hs_codes`` table. Rather than bulk-seed 5,600+
    placeholder rows, we lazily upsert exactly the code a proposal (or a human
    confirmation) needs, so ``product.hs_code``'s foreign key stays valid. A code
    absent from the engine seed returns ``None`` (never a fabricated row, I1).
    """
    existing = db.get(HSCode, code)
    if existing is not None:
        return existing
    row = _engine_hs_rows().get(code)
    if row is not None:
        name_en = (row.get("name_en") or "").strip()
        name_ar = (row.get("name_ar") or "").strip()
        hs = HSCode(
            code=code,
            description_en=name_en,
            # The seed leaves most name_ar blank; fall back to the English name so
            # the NOT NULL column always holds a real description, never an empty
            # string.
            description_ar=name_ar or name_en,
            level=len(code) if len(code) in {2, 4, 6} else 6,
        )
        db.add(hs)
        db.flush()
        return hs
    # The general classifier proposes codes from the FULL WCO nomenclature, not
    # only the seed CSV — backfill those from the engine's official reference
    # (real sourced data, mirroring the manual-confirm endpoint's backfill).
    from app.services import engine

    is_valid, description = engine.hs6_reference(code)
    if not is_valid:
        return None
    hs = HSCode(
        code=code,
        level=6,
        parent_code=code[:4],
        description_en=description or f"HS {code}",
        description_ar=description or f"رمز {code}",
    )
    db.add(hs)
    db.flush()
    return hs


def classify_product(db: Session, product: Product) -> list[dict]:
    """Propose up to three HS6 candidates for ``product`` via the engine (I1, I2).

    The query is the BARE product name — vision descriptions measurably lowered
    the old resolver's match scores (Wave 3 diagnosis, symptom A), so descriptive
    noise never enters the query; vision attributes instead feed the classifier
    as explicit hints. The engine's ``classify_general`` decides internally:
    deterministic seed analysis when it suffices (no LLM call, no spend), Claude
    over the full WCO nomenclature when it does not, every candidate validated by
    the engine's no-fabrication gate. ``tier="manual"`` — the classifier cannot
    decide (or no key) — is a declared gap: status ``failed``, NO candidates
    invented (the manual search/entry UI is the last resort).

    Commit rule (ADR-0009 + ADR-0010): on the engine's ``tier="auto"`` verdict
    (strict seed-anchored, or the LLM-decisive route) the winning code IS
    committed to ``product.hs_code``, provenance-tagged
    ``hs_auto_classified=True`` — never silently: a human-confirmed code is
    never overwritten, and ``hs_confirmed_by_user`` stays human-only (set
    solely by :func:`confirm_hs_code`). The commit is self-correcting: a fresh
    classification that no longer reaches ``tier="auto"`` clears a *prior
    machine* commit (a human-confirmed code is never cleared), so the product
    never keeps screening the world on a code the engine has stopped endorsing.
    Every other tier only proposes.
    """
    from app.services import engine

    name_query = " ".join(part for part in (product.name_en, product.name_ar) if part)
    # Vision attributes ([{name, value}, …]) are hints for the classifier, not
    # query noise — the engine treats them like ingredient/label signals.
    hints = [
        str(a.get("value"))
        for a in (product.attributes or [])
        if isinstance(a, dict) and a.get("value")
    ]
    result = engine.classify_hs_general(name_query, ingredients=hints or None)

    tier = result.get("tier")
    provider = f"silk_hs_classifier ({result.get('source')})"
    candidates: list[dict] = []
    if tier in ("auto", "candidates"):
        for row in result.get("candidates") or []:
            code = (row.get("hs6") or "").strip()
            if len(code) != 6 or not code.isdigit():
                continue
            known = ensure_hs_code(db, code)
            candidates.append(
                {
                    "code": code,
                    # The engine's measured overlap/model confidence — None means
                    # honestly unscored, never a fabricated number (I1).
                    "confidence": row.get("confidence"),
                    "rationale": row.get("reason_ar") or result.get("message") or "",
                    "description_en": known.description_en if known else None,
                    "description_ar": (known.description_ar if known else None)
                    or row.get("description_ar"),
                    "in_catalogue": known is not None,
                    # Provenance: which engine path produced this proposal, and
                    # whether a paid LLM call was involved (symptom A fix — the
                    # offline fallback is visible, never silent).
                    "provider": provider,
                    "used_llm": bool(result.get("used_llm")),
                }
            )

    product.hs_candidates = candidates
    product.classification_status = "classified" if candidates else "failed"
    if not candidates:
        product.failure_reason = (
            result.get("message") or "HS classification could not propose a code"
        )[:500]

    # ADR-0009 + ADR-0010 (owner decisions 2026-08-08): the engine's
    # tier="auto" verdict — strict seed-anchored, or the LLM-decisive route
    # (source="llm_decisive": explicit decisive claim + confidence/margin bar
    # + structural gate) — commits the winning code, tagged as
    # machine-committed. Guards: a human-confirmed code is NEVER overwritten
    # (human supremacy, I2), and the code must be catalogue-valid
    # (ensure_hs_code above) so the FK holds. tier="candidates" (a contested
    # verdict the model would not declare decisive) still proposes only.
    committed_now = False
    auto_code = (result.get("hs6") or "").strip() if tier == "auto" else ""
    if auto_code and not product.hs_confirmed_by_user:
        committed = next((c for c in candidates if c["code"] == auto_code), None)
        if committed is not None and committed["in_catalogue"]:
            product.hs_code = auto_code
            product.hs_auto_classified = True
            committed_now = True
            log.info(
                "hs_code_auto_committed",
                product_id=str(product.id),
                hs_code=auto_code,
                confidence=committed["confidence"],
                provider=provider,
            )
    # A prior MACHINE commit that this fresh classification no longer endorses
    # (tier downgraded to candidates/manual, or the new auto code is not
    # catalogue-valid) must not linger: clear it so the product reverts to
    # "needs a code" instead of screening the world on a code the engine just
    # declined to stand behind. A human-confirmed code (I2) is never touched —
    # only machine commits are self-correcting.
    if (
        not committed_now
        and product.hs_auto_classified
        and not product.hs_confirmed_by_user
    ):
        log.info(
            "hs_auto_commit_cleared_on_downgrade",
            product_id=str(product.id),
            previous_hs_code=product.hs_code,
            tier=tier,
        )
        product.hs_code = None
        product.hs_auto_classified = False

    db.flush()
    log.info(
        "product_classified",
        product_id=str(product.id),
        provider=provider,
        tier=tier,
        used_llm=bool(result.get("used_llm")),
        status=product.classification_status,
        candidates=[c["code"] for c in candidates],
    )
    return candidates


def confirm_hs_code(
    db: Session,
    product: Product,
    chosen_code: str,
    user_id: uuid.UUID | None,
) -> Product:
    """Record the user's HS choice, logging an override for classifier feedback.

    Backfills the catalogue first (:func:`ensure_hs_code`) so a human can confirm
    any real engine code even if it was never seeded — the committed ``hs_code``
    FK stays valid. This is the ONLY place ``hs_confirmed_by_user`` is set
    (invariant I2, human-only), and a human decision here supersedes any
    machine-committed code: the ``hs_auto_classified`` tag is cleared, and
    overriding an auto-committed code is logged as an :class:`HSCorrection`
    (classifier feedback, ADR-0009).
    """
    ensure_hs_code(db, chosen_code)

    # What did the machine put forward? An auto-COMMITTED code (ADR-0009) is the
    # strongest machine claim and takes precedence as "suggested" in the
    # correction ledger; otherwise the top proposal, as before.
    suggested = product.hs_candidates[0] if product.hs_candidates else None
    suggested_code = suggested["code"] if suggested else None
    if product.hs_auto_classified and product.hs_code:
        auto = next(
            (c for c in (product.hs_candidates or []) if c["code"] == product.hs_code),
            None,
        )
        suggested, suggested_code = auto or suggested, product.hs_code

    if suggested_code and suggested_code != chosen_code:
        db.add(
            HSCorrection(
                product_id=product.id,
                suggested_code=suggested_code,
                suggested_confidence=suggested["confidence"] if suggested else None,
                chosen_code=chosen_code,
                corrected_by=user_id,
            )
        )
        log.info(
            "hs_code_overridden",
            product_id=str(product.id),
            suggested=suggested_code,
            chosen=chosen_code,
        )

    product.hs_code = chosen_code
    product.hs_confirmed_by_user = True
    # A human decision supersedes any machine commit — the auto tag never
    # outlives a confirm/override (provenance stays truthful, ADR-0009).
    product.hs_auto_classified = False
    db.flush()
    return product
