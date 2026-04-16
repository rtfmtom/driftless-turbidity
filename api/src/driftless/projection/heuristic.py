"""Layer B — heuristic clarity model per README §6.B.

Encodes physical intuition about Driftless stream clarity as a
rules-based decision tree, ordered:

* If little rain and stage isn't rising → clear
* If light rain and the basin is mostly forest/pasture with strong
  baseflow → tinged
* If moderate rain → stained
* Otherwise → blown

The thresholds below are placeholders to be calibrated against logged
observations in Chunk 4. Keep changes here in sync with the calibration
script's expected parameter set.

Usage::

    # Project all watched streams now and persist
    python -m driftless.projection.heuristic --all-watched

    # Just one stream
    python -m driftless.projection.heuristic --stream-id 7
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from driftless.db.models import Projection, Stream
from driftless.db.session import SessionLocal
from driftless.projection.features import StreamFeatures, compute_features

logger = logging.getLogger(__name__)


MODEL_VERSION = "heuristic-1"

# Threshold defaults — README §6.B placeholders, slightly metricized.
THRESHOLDS = {
    "rain_24h_clear_mm": 5.0,        # below this with steady stage → clear
    "rain_24h_tinged_mm": 15.0,      # below this with friendly basin → tinged
    "rain_24h_stained_mm": 30.0,     # below this → stained, otherwise blown
    "stage_delta_6h_quiet_ft": 0.2,  # rise threshold for "steady"
    "row_crop_friendly_pct": 30.0,   # below this is "friendly" basin
    "baseflow_strong": 0.6,          # baseline strong-baseflow threshold
}

# Projection validity window. Heuristic uses near-real-time inputs, so
# the projection is conceptually about *now* + the next ~6 hours.
VALID_HORIZON_HOURS = 6


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ProjectionDecision:
    clarity_class: str  # 'clear' | 'tinged' | 'stained' | 'blown'
    confidence: str     # 'low' | 'medium' | 'high'
    rationale: str
    rule: str           # which branch fired


@dataclass
class ProjectResult:
    stream_id: int
    stream_name: str
    status: str  # 'ok' | 'failed' | 'skipped'
    clarity_class: str | None = None
    confidence: str | None = None
    message: str = ""


@dataclass
class ProjectStats:
    results: list[ProjectResult] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out = {"ok": 0, "failed": 0, "skipped": 0}
        for r in self.results:
            out[r.status] = out.get(r.status, 0) + 1
        return out


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def decide(features: StreamFeatures) -> ProjectionDecision:
    """Map a feature snapshot to a clarity class + confidence."""
    r24 = features.rainfall_24h_mm
    sdelta = features.stage_delta_6h_ft
    row_crop = features.pct_row_crop
    bfi = features.baseflow_index

    th = THRESHOLDS

    # Inputs we can't recover from cleanly.
    if r24 is None:
        return ProjectionDecision(
            clarity_class="stained",
            confidence="low",
            rationale="no rainfall data; defaulting to 'stained' as a neutral middle estimate",
            rule="missing_rainfall",
        )

    # Rule 1: clear — quiet conditions all around.
    if r24 < th["rain_24h_clear_mm"] and (
        sdelta is None or sdelta < th["stage_delta_6h_quiet_ft"]
    ):
        conf = "high" if sdelta is not None else "medium"
        rationale = (
            f"24h rainfall {r24:.1f} mm < {th['rain_24h_clear_mm']:.0f} mm threshold"
        )
        if sdelta is not None:
            rationale += f" and 6h stage Δ {sdelta:+.2f} ft is quiet"
        return ProjectionDecision("clear", conf, rationale, rule="r1_clear")

    # Rule 2: tinged — light rain on a friendly basin (low row crop, strong baseflow).
    # Treat unknown baseflow as "strong enough" — Driftless streams are
    # mostly spring-fed; this is the locally-correct prior. The calibration
    # step will tighten this once we have real BFI numbers.
    bfi_ok = bfi is None or bfi >= th["baseflow_strong"]
    row_crop_ok = row_crop is not None and row_crop < th["row_crop_friendly_pct"]
    if r24 < th["rain_24h_tinged_mm"] and row_crop_ok and bfi_ok:
        conf = "medium"
        rationale = (
            f"24h rainfall {r24:.1f} mm < {th['rain_24h_tinged_mm']:.0f} mm, "
            f"row crop {row_crop:.0f}% < {th['row_crop_friendly_pct']:.0f}% threshold"
        )
        if bfi is not None:
            rationale += f", baseflow index {bfi:.2f}"
        return ProjectionDecision("tinged", conf, rationale, rule="r2_tinged")

    # Rule 3: stained — moderate rain.
    if r24 < th["rain_24h_stained_mm"]:
        return ProjectionDecision(
            "stained",
            "medium",
            f"24h rainfall {r24:.1f} mm in stained band [{th['rain_24h_tinged_mm']:.0f}, {th['rain_24h_stained_mm']:.0f}) mm",
            rule="r3_stained",
        )

    # Rule 4: blown — heavy rain.
    return ProjectionDecision(
        "blown",
        "high",
        f"24h rainfall {r24:.1f} mm exceeds {th['rain_24h_stained_mm']:.0f} mm — basin is loaded",
        rule="r4_blown",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist(session: Session, features: StreamFeatures, decision: ProjectionDecision) -> None:
    snapshot = features.to_snapshot()
    snapshot["thresholds"] = THRESHOLDS
    snapshot["rule"] = decision.rule
    snapshot["rationale"] = decision.rationale

    valid_to = features.computed_at + timedelta(hours=VALID_HORIZON_HOURS)

    stmt = pg_insert(Projection.__table__).values(
        stream_id=features.stream_id,
        computed_at=features.computed_at,
        valid_from=features.computed_at,
        valid_to=valid_to,
        clarity_class=decision.clarity_class,
        confidence=decision.confidence,
        feature_snapshot=snapshot,
        model_version=MODEL_VERSION,
    )
    # Idempotent on (stream_id, computed_at): re-running the same hour just
    # overwrites with the latest decision.
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            Projection.__table__.c.stream_id,
            Projection.__table__.c.computed_at,
        ],
        set_={
            "valid_from": stmt.excluded.valid_from,
            "valid_to": stmt.excluded.valid_to,
            "clarity_class": stmt.excluded.clarity_class,
            "confidence": stmt.excluded.confidence,
            "feature_snapshot": stmt.excluded.feature_snapshot,
            "model_version": stmt.excluded.model_version,
        },
    )
    session.execute(stmt)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def project_one(session: Session, stream: Stream, now: datetime | None = None) -> ProjectResult:
    features = compute_features(session, stream.id, now=now)
    if features is None:
        return ProjectResult(
            stream_id=stream.id,
            stream_name=stream.name,
            status="skipped",
            message="stream not found",
        )

    decision = decide(features)
    _persist(session, features, decision)
    session.commit()
    return ProjectResult(
        stream_id=stream.id,
        stream_name=stream.name,
        status="ok",
        clarity_class=decision.clarity_class,
        confidence=decision.confidence,
        message=decision.rationale,
    )


def project_all_watched(
    session: Session,
    stream_ids: Iterable[int] | None = None,
    now: datetime | None = None,
) -> ProjectStats:
    stmt = select(Stream)
    if stream_ids is not None:
        stmt = stmt.where(Stream.id.in_(list(stream_ids)))
    else:
        stmt = stmt.where(Stream.is_watched.is_(True))
    stmt = stmt.order_by(Stream.id)

    stats = ProjectStats()
    for stream in session.scalars(stmt):
        try:
            res = project_one(session, stream, now=now)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("Projection failed for stream %d", stream.id)
            res = ProjectResult(
                stream_id=stream.id,
                stream_name=stream.name,
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
        stats.results.append(res)
        logger.info(
            "Projection [%s]: %s (%s) — %s",
            res.status,
            res.stream_name,
            res.clarity_class,
            res.message,
        )
    return stats


def project_once_job() -> None:
    """Scheduler entry point."""
    session = SessionLocal()
    try:
        project_all_watched(session)
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled projection run failed")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the heuristic projection model")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all-watched", action="store_true", help="Project every watched stream (default)")
    group.add_argument(
        "--stream-id",
        type=int,
        action="append",
        dest="stream_ids",
        help="Project a specific stream by id (repeatable)",
    )
    parser.add_argument(
        "--at",
        type=str,
        default=None,
        help="Override 'now' for backfill/testing (ISO 8601 UTC)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    now = None
    if args.at:
        s = args.at.replace(" ", "T")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        now = datetime.fromisoformat(s)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

    session = SessionLocal()
    try:
        stats = project_all_watched(session, stream_ids=args.stream_ids, now=now)
    finally:
        session.close()

    summary = stats.summary()
    print(summary)
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
