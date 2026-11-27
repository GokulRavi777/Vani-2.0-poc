from typing import TypedDict, List, Dict, Any, Optional, Literal
from vani.schemas.models import InterviewStateEnum, InterviewIntentEnum

class InterviewState(TypedDict, total=False):
    # Session Identifiers
    session_id: str
    selected_skill: Optional[str]
    selected_sub_skill: Optional[str]
    
    # Question Tracking & Strict Limits
    current_question_id: Optional[str]
    current_question_text: Optional[str]
    current_question_topic: Optional[str]
    current_expected_concepts: List[str]
    primary_question_count: int
    max_primary_questions: int
    remaining_questions: int
    follow_up_count_for_current_question: int
    max_follow_ups_per_question: int
    
    # History & Session Memory
    presented_questions: List[str]
    candidate_answers: List[Dict[str, Any]]
    concepts_mentioned: List[str]
    unclear_or_missing_concepts: List[str]
    follow_up_history: List[Dict[str, Any]]
    
    # Conversational Workflow & Control
    current_state: str
    previous_state: Optional[str]
    current_intent: str
    stage_1_route: Optional[str]
    stage_2_route: Optional[str]
    ack_text: Optional[str]
    follow_up_text: Optional[str]
    is_paused: bool
    is_completed: bool
    rolling_summary: str
    
    # Utterance inputs & outputs for current turn
    candidate_utterance: str
    agent_response: str
    decision_reasoning: str
    proposed_action: str

    # Phase 1 & Universal Policy Fields
    stage_1_status: str  # NOT_STARTED, IN_PROGRESS, READY_FOR_PHASE_2, TERMINATED
    greeting_completed: bool
    off_topic_count: int
    warning_level: int
    readiness_status: str  # PENDING, READY, NOT_READY
    wait_reason: Optional[str]  # NERVOUSNESS, REQUEST_TIME
    wait_started_at: Optional[float]
    readiness_confirmation_count: int
    clarification_count: int
    session_status: str  # ACTIVE, TERMINATED
    termination_reason: Optional[str]

    # Dynamic Skip and Revisit State
    skip_intent: Optional[Literal["SKIP_REQUEST", "OTHER"]]
    skip_preference: Optional[Literal["PENDING", "SKIP_ENTIRELY", "REVISIT_AFTER_NEXT", "ANSWERED", "UNRESOLVED"]]
    original_skip_request: Optional[str]
    candidate_clarification_response: Optional[str]
    clarification_retry_count: int
    question_visit_mode: Literal["INITIAL", "REVISIT"]
    skipped_question_ids: List[str]
    revisit_queue: List[Dict[str, Any]]
    revisited_question_ids: List[str]
    q2_revisit_completed: bool
    q3_completed: bool
    current_transition_reason: Optional[str]

    # Stage 2 Per-Question State Contract & FIFO Revisit Queue Tracking
    question_state: Dict[str, Dict[str, Any]]
    active_question_stage: str  # STAGE_2_PRIMARY, STAGE_2_REVISIT, STAGE_2_COMPLETE, STAGE_3_CONCLUSION
    answer_timer_duration: float
    answer_capture_state: str  # WAITING_FOR_ANSWER, ANSWER_CAPTURE_IN_PROGRESS, ANSWER_RECEIVED

    # Stage 3 Conclusion & Assessment Finalization Fields
    terminal_outcome: Optional[str]  # COMPLETED, TERMINATED_BY_CANDIDATE, TERMINATED_BY_GUARDRAIL, TERMINATED_BY_SYSTEM_ERROR
    conclusion_started: bool
    assessment_finalized: bool
    final_response_delivered: bool
    cleanup_started: bool
    cleanup_completed: bool
    final_assessment: Optional[Dict[str, Any]]
