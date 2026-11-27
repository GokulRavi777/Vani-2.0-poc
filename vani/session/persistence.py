"""
Persists completed/terminated interview conversations and evaluation summaries to PostgreSQL/SQLite.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from backend.app.database import SessionLocal
from backend.app.models import InterviewSession
from vani.session.manager import SessionState

logger = logging.getLogger("vani.session.persistence")


def persist_session_evaluation(session: SessionState) -> bool:
    """Stores full conversation turns and evaluation summary on the InterviewSession row.

    Returns True if an existing InterviewSession row was updated, False otherwise.
    """
    assessment = session.finalize_assessment()
    transcript_payload = {
        "session_id": session.session_id,
        "selected_skill": session.selected_skill,
        "selected_sub_skill": session.selected_sub_skill,
        "conversation_turns": session.conversation_turns,
        "candidate_answers": session.candidate_answers,
        "follow_up_history": session.follow_up_history,
    }

    db = SessionLocal()
    try:
        row: Optional[InterviewSession] = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == session.session_id)
            .first()
        )
        if not row:
            logger.debug("No InterviewSession DB row for %s (CLI/unit-test session); skipping DB persist.", session.session_id)
            return False

        row.session_status = session.session_status
        row.terminal_outcome = session.terminal_outcome
        row.termination_reason = session.termination_reason
        if session.completed_at:
            row.completed_at = datetime.utcfromtimestamp(session.completed_at)
            row.duration_seconds = round(session.completed_at - session.started_at, 2)
        row.transcript_json = json.dumps(transcript_payload)
        row.assessment_summary_json = json.dumps(assessment)
        db.commit()
        logger.info(
            "Persisted interview evaluation for session %s (candidate=%s, outcome=%s)",
            session.session_id,
            row.candidate_id,
            row.terminal_outcome,
        )
        return True
    except Exception as exc:
        logger.error("Failed to persist evaluation for session %s: %s", session.session_id, exc)
        db.rollback()
        return False
    finally:
        db.close()
