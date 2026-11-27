"""
SQLAlchemy ORM models for VANI 2.0 Candidate Portal and Assessment Tracking.
"""

from datetime import datetime
import json
from sqlalchemy import Boolean, Column, String, Integer, Float, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.app.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(String(36), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("InterviewSession", back_populates="candidate")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(String(36), primary_key=True, index=True)
    candidate_id = Column(String(36), ForeignKey("candidates.id"), nullable=False)
    selected_skill = Column(String(64), default="Python", nullable=False)
    room_name = Column(String(128), unique=True, index=True, nullable=False)
    session_status = Column(String(32), default="CREATED", nullable=False)
    # CREATED, READY, CONNECTING, IN_PROGRESS, COMPLETED, TERMINATED, FAILED

    terminal_outcome = Column(String(64), nullable=True)
    # COMPLETED, TERMINATED_BY_CANDIDATE, TERMINATED_BY_GUARDRAIL, TERMINATED_BY_SYSTEM_ERROR

    termination_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, default=0.0)

    # Serialized JSON result fields
    transcript_json = Column(Text, default="[]")
    assessment_summary_json = Column(Text, default="{}")

    candidate = relationship("Candidate", back_populates="sessions")


class MotherSkill(Base):
    """Primary table storing top-level interview domains (e.g., Python, Java, SQL)."""

    __tablename__ = "mother_skills"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(64), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sub_skills = relationship(
        "SubSkill",
        back_populates="mother_skill",
        cascade="all, delete-orphan",
    )


class SubSkill(Base):
    """Secondary table storing specialized skills & few-shot prompts under each MotherSkill."""

    __tablename__ = "sub_skills"
    __table_args__ = (
        UniqueConstraint("mother_skill_id", "name", name="uq_mother_sub_skill"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    mother_skill_id = Column(
        Integer,
        ForeignKey("mother_skills.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name = Column(String(100), index=True, nullable=False)
    description = Column(Text, nullable=False)
    topics_json = Column(Text, default="[]", nullable=False)
    difficulty_levels_json = Column(Text, default='["Beginner", "Intermediate"]', nullable=False)
    system_prompt = Column(Text, nullable=False)
    few_shot_prompt = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    mother_skill = relationship("MotherSkill", back_populates="sub_skills")
