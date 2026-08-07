"""Analysis liveness heartbeat for long-running funnel stages (symptom B).

``reconcile_stuck_analyses`` fails any analysis whose row hasn't been updated
inside the staleness window — but stage 2/3 write only ``CountryRanking`` rows
mid-run, so a legitimately long (live-vendor) run looked dead and was reaped
with "stalled … (worker lost)". Each stage loop now beats the analysis row in
its own short transaction (independent of the stage's main transaction, so the
reaper sees it immediately and a stage rollback never rolls the heartbeat
back).
"""

from __future__ import annotations

import uuid

from sqlalchemy import update

from app.logging import get_logger

log = get_logger(__name__)


def beat(analysis_id: uuid.UUID) -> None:
    """Stamp ``analyses.updated_at`` now, in an independent short transaction.

    Best-effort: a heartbeat failure must never fail the stage doing real work.
    """
    from app.db import SessionLocal
    from app.models import Analysis, utcnow

    try:
        with SessionLocal() as hb:
            hb.execute(
                update(Analysis).where(Analysis.id == analysis_id).values(updated_at=utcnow())
            )
            hb.commit()
    except Exception as exc:  # noqa: BLE001 — liveness signal only
        log.warning("analysis_heartbeat_failed", analysis_id=str(analysis_id), error=str(exc))
