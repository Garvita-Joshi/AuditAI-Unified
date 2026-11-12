"""Autonomous Sourcing Background Worker for AuditAI.
Runs 24/7 in the FastAPI background (independent of active frontend sessions / browser windows):
1. Connects to Gmail IMAP in batch mode to detect vendor quotations and counteroffer replies.
2. Accurately extracts price, lead time, warranty, payment terms via Gemini & structured rules.
3. Automatically executes company procurement policy negotiations (e.g. Round 1 counteroffers)
   and auto-dispatches follow-ups.
4. Keeps sourcing mind maps, quotation statuses, and winner recommendations fully updated.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("autonomous_worker")

# Shared runtime worker telemetry
_worker_stats = {
    "is_running": False,
    "last_tick_at": None,
    "last_error": None,
    "total_cycles": 0,
    "active_runs_tracked": 0,
    "replies_processed_total": 0,
}


def get_worker_status() -> dict:
    """Return runtime telemetry about the autonomous background worker."""
    return dict(_worker_stats)


def _run_worker_tick():
    """Synchronous worker tick executed in a background thread."""
    from backend.app.db import SessionLocal
    from backend.app.models.auth import User
    from backend.app.agentic_ai.records import AgentRun, AgentVendor
    from backend.app.api.sourcing import SourcingRequest, is_archived, process_autonomous_sourcing_cycle
    from backend.app.agentic_ai.messaging import fetch_all_inbox_replies

    _worker_stats["last_tick_at"] = datetime.utcnow().isoformat()
    _worker_stats["total_cycles"] += 1

    with SessionLocal() as db:
        # 1. Query active, unarchived runs created within the last 14 days
        cutoff = datetime.utcnow() - timedelta(days=14)
        candidate_runs = (
            db.query(AgentRun)
            .filter(AgentRun.created_at >= cutoff)
            .order_by(AgentRun.id.desc())
            .all()
        )

        active_run_ids = []
        for run in candidate_runs:
            if is_archived(db, 'sourcing', run.request_id):
                continue
            row = db.query(SourcingRequest).filter_by(id=run.request_id).first()
            if not row:
                continue
            has_outreach = db.query(AgentVendor).filter(
                AgentVendor.run_id == run.id,
                (AgentVendor.sent_at.isnot(None) | (AgentVendor.status == 'draft_ready'))
            ).first()
            if has_outreach:
                active_run_ids.append((run.id, row.id, run.owner_id))

        _worker_stats["active_runs_tracked"] = len(active_run_ids)
        if not active_run_ids:
            return

    # 2. Single-connection IMAP batch pull for all active runs
    replies_by_run = {}
    try:
        replies_by_run = fetch_all_inbox_replies(max_messages=40)
    except Exception as imap_err:
        logger.debug("Background worker IMAP batch pull notice: %s", imap_err)
        replies_by_run = {}

    # 3. Process each active run autonomously in its own isolated transaction
    for run_id, request_id, owner_id in active_run_ids:
        with SessionLocal() as db:
            try:
                run = db.query(AgentRun).filter_by(id=run_id).first()
                row = db.query(SourcingRequest).filter_by(id=request_id).first()
                if not run or not row:
                    continue
                user = db.query(User).filter_by(id=owner_id).first()
                user_email = user.email if user and user.email else ""
                run_replies = replies_by_run.get(run_id, [])

                if run_replies:
                    _worker_stats["replies_processed_total"] += len(run_replies)
                    logger.info(
                        "Autonomous worker found %d reply(ies) for Run %d (Req %d). Processing cycle...",
                        len(run_replies), run_id, request_id
                    )

                process_autonomous_sourcing_cycle(
                    db=db,
                    run=run,
                    row=row,
                    user_email=user_email,
                    dispatch_pending=True,
                    poll_inbox=False,
                    prefetched_replies=run_replies,
                )
                db.commit()
            except Exception as run_err:
                db.rollback()
                logger.debug("Background autonomous cycle for run %d skipped: %s", run_id, run_err)
                _worker_stats["last_error"] = str(run_err)


async def start_autonomous_sourcing_worker(poll_interval_seconds: int = 15):
    """Async background task that periodically runs the autonomous sourcing cycle."""
    _worker_stats["is_running"] = True
    logger.info("Autonomous Sourcing Background Worker started (interval=%ds).", poll_interval_seconds)

    while True:
        try:
            await asyncio.to_thread(_run_worker_tick)
        except asyncio.CancelledError:
            logger.info("Autonomous Sourcing Background Worker cancelled.")
            break
        except Exception as e:
            logger.exception("Error in autonomous sourcing worker tick: %s", e)
            _worker_stats["last_error"] = str(e)

        try:
            await asyncio.sleep(poll_interval_seconds)
        except asyncio.CancelledError:
            break

    _worker_stats["is_running"] = False


async def stop_autonomous_sourcing_worker(task: Optional[asyncio.Task]):
    """Safely terminate the background worker during application shutdown."""
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _worker_stats["is_running"] = False
    logger.info("Autonomous Sourcing Background Worker stopped.")

