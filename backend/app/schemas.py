"""
Pydantic schemas for request/response validation in VANI 2.0 API.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    candidate_id: str
    name: str
    email: str


class CandidateResponse(BaseModel):
    id: str
    name: str
    email: str


class SubSkillItem(BaseModel):
    id: int
    name: str
    description: str
    topics: List[str] = []
    difficulty_levels: List[str] = []


class SkillItem(BaseModel):
    id: str
    name: str
    category: str
    description: str
    available: bool = True
    sub_skills: List[SubSkillItem] = []


class SkillsResponse(BaseModel):
    skills: List[SkillItem]


class CreateSessionRequest(BaseModel):
    skill: str = "Python"
    sub_skill: Optional[str] = None


class StartSessionResponse(BaseModel):
    session_id: str
    room_name: str
    livekit_url: str
    token: str
    skill: str
    status: str


class SessionStatusResponse(BaseModel):
    id: str
    candidate_id: str
    selected_skill: str
    room_name: str
    session_status: str
    terminal_outcome: Optional[str] = None
    termination_reason: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0


class CompleteSessionRequest(BaseModel):
    terminal_outcome: Optional[str] = "COMPLETED"
    reason: Optional[str] = "NORMAL_CONCLUSION"


class AssessmentResultResponse(BaseModel):
    session_id: str
    candidate_id: str
    selected_skill: str
    session_status: str
    terminal_outcome: Optional[str]
    duration_seconds: float
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    summary_metrics: Dict[str, Any] = {}
    question_history: Dict[str, Any] = {}
    candidate_answers: List[Dict[str, Any]] = []
