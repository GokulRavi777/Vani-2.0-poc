"""
FastAPI Application Entrypoint: Endpoints for Auth, Skills, Sessions, LiveKit Tokens & Results.
"""

import uuid
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config.settings import settings
from backend.app.database import engine, Base, get_db
from backend.app.models import Candidate, InterviewSession
from backend.app.schemas import (
    LoginRequest, LoginResponse, CandidateResponse,
    SkillsResponse, SkillItem, SubSkillItem, CreateSessionRequest,
    StartSessionResponse, SessionStatusResponse,
    CompleteSessionRequest, AssessmentResultResponse,
)
from backend.app.auth import (
    hash_password, verify_password, create_access_token, decode_access_token
)
from backend.app.livekit_service import livekit_service
from vani.mcp.skill_prompt_repo import (
    ensure_skill_prompts_seeded,
    get_skill_prompt_from_db,
    list_skills_from_db,
)
from vani.session.manager import session_manager

logger = logging.getLogger("vani.backend.main")

# Initialize database schema
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="VANI 2.0 Candidate Portal API",
    description="Backend API powering the candidate voice assessment experience.",
    version="2.0.0",
)

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
@app.head("/")
def health_check():
    """Root health check for Render and load balancers."""
    return {"status": "ok", "service": "VANI 2.0 Interview Platform"}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# Seed default candidate account if not present
def seed_default_candidate():
    from backend.app.database import SessionLocal
    db = SessionLocal()
    try:
        user = db.query(Candidate).filter(Candidate.email == "candidate@vani.ai").first()
        if not user:
            default_candidate = Candidate(
                id=str(uuid.uuid4()),
                email="candidate@vani.ai",
                name="Demo Candidate",
                password_hash=hash_password("candidate123"),
            )
            db.add(default_candidate)
            db.commit()
            logger.info("Default candidate seeded: candidate@vani.ai / candidate123")
        else:
            # Sync password hash with current hashing implementation
            user.password_hash = hash_password("candidate123")
            db.commit()
    finally:
        db.close()

seed_default_candidate()


# Dependency to resolve authenticated candidate
def get_current_candidate(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Candidate:
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    candidate = db.query(Candidate).filter(Candidate.id == payload["sub"]).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return candidate


# -------------------------------------------------------------
# Auth Endpoints
# -------------------------------------------------------------
@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    email_clean = (req.email or "").strip().lower()
    candidate = db.query(Candidate).filter(Candidate.email == email_clean).first()
    
    # Auto-seed demo candidate on the fly if needed
    if not candidate and email_clean == "candidate@vani.ai" and req.password == "candidate123":
        candidate = Candidate(
            id=str(uuid.uuid4()),
            email="candidate@vani.ai",
            name="Demo Candidate",
            password_hash=hash_password("candidate123"),
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)

    if not candidate or not verify_password(req.password, candidate.password_hash):
        # Fallback sync for demo account if password was candidate123
        if candidate and candidate.email == "candidate@vani.ai" and req.password == "candidate123":
            candidate.password_hash = hash_password("candidate123")
            db.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

    access_token = create_access_token({"sub": candidate.id, "email": candidate.email})
    return LoginResponse(
        access_token=access_token,
        candidate_id=candidate.id,
        name=candidate.name,
        email=candidate.email,
    )


@app.get("/api/auth/me", response_model=CandidateResponse)
def get_me(candidate: Candidate = Depends(get_current_candidate)):
    return CandidateResponse(id=candidate.id, name=candidate.name, email=candidate.email)


# -------------------------------------------------------------
# Skills Endpoint (DB-Backed MotherSkill -> SubSkill Tree)
# -------------------------------------------------------------
def _split_skill_label(raw_skill: str) -> tuple[str, Optional[str]]:
    if "::" in raw_skill:
        mother, sub = raw_skill.split("::", 1)
        return mother.strip(), sub.strip() or None
    return raw_skill.strip(), None


@app.get("/api/skills", response_model=SkillsResponse)
def get_available_skills(db: Session = Depends(get_db)):
    db_skills = list_skills_from_db(db=db)
    items: list[SkillItem] = []
    for m in db_skills:
        sub_items = [
            SubSkillItem(
                id=sub["id"],
                name=sub["sub_skill"],
                description=sub["description"],
                topics=sub["topics"],
                difficulty_levels=sub["difficulty_levels"],
            )
            for sub in m["sub_skills"]
        ]
        items.append(
            SkillItem(
                id=str(m["id"]),
                name=m["skill_name"],
                category="Mother Skill",
                description=m["description"],
                available=True,
                sub_skills=sub_items,
            )
        )
    return SkillsResponse(skills=items)


# -------------------------------------------------------------
# Session Lifecycle Endpoints
# -------------------------------------------------------------
@app.post("/api/sessions", response_model=SessionStatusResponse)
def create_session(
    req: CreateSessionRequest,
    candidate: Candidate = Depends(get_current_candidate),
    db: Session = Depends(get_db),
):
    mother_name, parsed_sub = _split_skill_label(req.skill)
    requested_sub = req.sub_skill or parsed_sub
    record = get_skill_prompt_from_db(mother_name, sub_skill_name=requested_sub, db=db)
    if not record:
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{req.skill}' (sub_skill='{requested_sub}') is not configured in the database.",
        )

    stored_label = (
        f"{record['mother_skill']} :: {record['sub_skill']}"
        if requested_sub
        else record["mother_skill"]
    )
    session_id = f"vani_session_{uuid.uuid4().hex[:12]}"
    room_name = session_id  # Session ID matches room name for 1:1 isolation

    sess = InterviewSession(
        id=session_id,
        candidate_id=candidate.id,
        selected_skill=stored_label,
        room_name=room_name,
        session_status="CREATED",
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)

    agent_sess = session_manager.get_or_create(room_name)
    agent_sess.selected_skill = record["mother_skill"]
    agent_sess.selected_sub_skill = record["sub_skill"] if requested_sub else None
    return sess


@app.post("/api/sessions/{session_id}/start", response_model=StartSessionResponse)
async def start_session(
    session_id: str,
    candidate: Candidate = Depends(get_current_candidate),
    db: Session = Depends(get_db),
):
    sess = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.candidate_id == candidate.id,
    ).first()

    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    if sess.session_status in ["COMPLETED", "TERMINATED", "FAILED"]:
        raise HTTPException(status_code=400, detail="Cannot start a closed or completed session.")

    already_dispatched = sess.session_status != "CREATED"
    sess.session_status = "CONNECTING"
    if not sess.started_at:
        sess.started_at = datetime.utcnow()
    db.commit()

    mother_skill, sub_skill = _split_skill_label(sess.selected_skill)
    agent_sess = session_manager.get_or_create(sess.room_name)
    agent_sess.selected_skill = mother_skill
    agent_sess.selected_sub_skill = sub_skill
    room_meta = {"session_id": sess.id, "skill": mother_skill, "sub_skill": sub_skill}

    # Generate candidate LiveKit Token
    token = livekit_service.generate_candidate_token(
        room_name=sess.room_name,
        participant_identity=f"candidate_{candidate.id[:8]}",
        participant_name=candidate.name,
        metadata=room_meta,
    )

    # Dispatch VANI agent to room only on initial session creation
    if not already_dispatched:
        await livekit_service.dispatch_agent(sess.room_name, metadata=room_meta)

    return StartSessionResponse(
        session_id=sess.id,
        room_name=sess.room_name,
        livekit_url=settings.LIVEKIT_URL,
        token=token,
        skill=sess.selected_skill,
        status=sess.session_status,
    )


@app.get("/api/sessions/{session_id}", response_model=SessionStatusResponse)
def get_session_status(
    session_id: str,
    candidate: Candidate = Depends(get_current_candidate),
    db: Session = Depends(get_db),
):
    sess = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.candidate_id == candidate.id,
    ).first()

    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    # Sync live state from agent session manager if active
    agent_sess = session_manager.get(sess.room_name)
    if agent_sess:
        if agent_sess.is_terminated():
            sess.session_status = agent_sess.session_status
            sess.terminal_outcome = agent_sess.terminal_outcome
            sess.termination_reason = agent_sess.termination_reason
            if agent_sess.completed_at and not sess.completed_at:
                sess.completed_at = datetime.fromtimestamp(agent_sess.completed_at)
                sess.duration_seconds = round(agent_sess.completed_at - agent_sess.started_at, 2)
            db.commit()

    return sess


@app.post("/api/sessions/{session_id}/complete")
def complete_session(
    session_id: str,
    req: CompleteSessionRequest,
    candidate: Candidate = Depends(get_current_candidate),
    db: Session = Depends(get_db),
):
    sess = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.candidate_id == candidate.id,
    ).first()

    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    # Authoritative check: consult live agent state
    agent_sess = session_manager.get(sess.room_name)
    if agent_sess:
        final_assessment = agent_sess.finalize_assessment()
        sess.session_status = agent_sess.session_status
        sess.terminal_outcome = agent_sess.terminal_outcome or req.terminal_outcome
        sess.termination_reason = agent_sess.termination_reason or req.reason
        if agent_sess.completed_at:
            sess.completed_at = datetime.fromtimestamp(agent_sess.completed_at)
            sess.duration_seconds = round(agent_sess.completed_at - agent_sess.started_at, 2)
        sess.assessment_summary_json = json.dumps(final_assessment)
    else:
        # Fallback if already cleaned up
        if not sess.completed_at:
            sess.completed_at = datetime.utcnow()
            if sess.started_at:
                sess.duration_seconds = (sess.completed_at - sess.started_at).total_seconds()
        sess.session_status = "COMPLETED"
        sess.terminal_outcome = req.terminal_outcome

    db.commit()
    return {"status": "success", "session_status": sess.session_status, "outcome": sess.terminal_outcome}


@app.post("/api/sessions/{session_id}/terminate")
def terminate_session(
    session_id: str,
    candidate: Candidate = Depends(get_current_candidate),
    db: Session = Depends(get_db),
):
    sess = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.candidate_id == candidate.id,
    ).first()

    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    agent_sess = session_manager.get(sess.room_name)
    if agent_sess:
        agent_sess.terminate_session("TERMINATED_BY_CANDIDATE")
        agent_sess.mark_cleanup_completed()
        sess.session_status = "TERMINATED"
        sess.terminal_outcome = "TERMINATED_BY_CANDIDATE"
        sess.termination_reason = "CANDIDATE_REQUESTED_TERMINATION"
    else:
        sess.session_status = "TERMINATED"
        sess.terminal_outcome = "TERMINATED_BY_CANDIDATE"

    if not sess.completed_at:
        sess.completed_at = datetime.utcnow()
        if sess.started_at:
            sess.duration_seconds = (sess.completed_at - sess.started_at).total_seconds()

    db.commit()
    return {"status": "terminated", "terminal_outcome": sess.terminal_outcome}


# -------------------------------------------------------------
# Results Retrieval Endpoint
# -------------------------------------------------------------
@app.get("/api/results/{session_id}", response_model=AssessmentResultResponse)
def get_assessment_result(
    session_id: str,
    candidate: Candidate = Depends(get_current_candidate),
    db: Session = Depends(get_db),
):
    sess = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.candidate_id == candidate.id,
    ).first()

    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    summary_metrics = {}
    question_history = {}
    candidate_answers = []

    # Check database stored assessment
    if sess.assessment_summary_json and sess.assessment_summary_json != "{}":
        try:
            data = json.loads(sess.assessment_summary_json)
            summary_metrics = data.get("summary_metrics", {})
            question_history = data.get("question_history", {})
            candidate_answers = data.get("candidate_answers", [])
        except Exception:
            pass

    # Or inspect live agent session if still in memory
    agent_sess = session_manager.get(sess.room_name)
    if agent_sess and agent_sess.final_assessment:
        fa = agent_sess.final_assessment
        summary_metrics = fa.get("summary_metrics", summary_metrics)
        question_history = fa.get("question_history", question_history)
        candidate_answers = fa.get("candidate_answers", candidate_answers)

    return AssessmentResultResponse(
        session_id=sess.id,
        candidate_id=sess.candidate_id,
        selected_skill=sess.selected_skill,
        session_status=sess.session_status,
        terminal_outcome=sess.terminal_outcome,
        duration_seconds=sess.duration_seconds,
        started_at=sess.started_at,
        completed_at=sess.completed_at,
        summary_metrics=summary_metrics,
        question_history=question_history,
        candidate_answers=candidate_answers,
    )
