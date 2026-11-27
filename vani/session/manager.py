import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from config.settings import settings

@dataclass
class SessionState:
    session_id: str
    selected_skill: Optional[str] = None
    selected_sub_skill: Optional[str] = None
    current_question_id: Optional[str] = None
    current_question_text: Optional[str] = None
    current_question_topic: Optional[str] = None
    current_expected_concepts: List[str] = field(default_factory=list)
    
    # Strict Question Limits & Universal Countdown
    primary_question_count: int = 0
    max_primary_questions: int = settings.MAX_PRIMARY_QUESTIONS
    remaining_questions: int = settings.MAX_PRIMARY_QUESTIONS
    follow_up_count_for_current_question: int = 0
    max_follow_ups_per_question: int = settings.MAX_FOLLOW_UPS_PER_QUESTION

    # Session History & Context
    presented_questions: List[str] = field(default_factory=list)
    candidate_answers: List[Dict[str, Any]] = field(default_factory=list)
    conversation_turns: List[Dict[str, Any]] = field(default_factory=list)
    concepts_mentioned: List[str] = field(default_factory=list)
    unclear_or_missing_concepts: List[str] = field(default_factory=list)
    follow_up_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Workflow State
    current_state: str = "GREETING"
    previous_state: Optional[str] = None
    is_paused: bool = False
    is_completed: bool = False
    rolling_summary: str = ""
    last_speech_time: float = field(default_factory=time.time)
    last_agent_utterance: str = ""

    # Phase 1 & Universal Policy Fields
    stage_1_status: str = "NOT_STARTED"  # NOT_STARTED, IN_PROGRESS, READY_FOR_PHASE_2, TERMINATED
    greeting_completed: bool = False
    off_topic_count: int = 0
    warning_level: int = 0
    readiness_status: str = "PENDING"  # PENDING, READY, NOT_READY
    wait_reason: Optional[str] = None  # NERVOUSNESS, REQUEST_TIME
    wait_started_at: Optional[float] = None
    readiness_confirmation_count: int = 0
    clarification_count: int = 0
    session_status: str = "ACTIVE"  # ACTIVE, TERMINATED, COMPLETED, CLOSED
    termination_reason: Optional[str] = None
    terminal_outcome: Optional[str] = None  # COMPLETED, TERMINATED_BY_CANDIDATE, TERMINATED_BY_GUARDRAIL, TERMINATED_BY_SYSTEM_ERROR

    # Stage 3 Conclusion & Assessment Finalization Fields
    conclusion_started: bool = False
    assessment_finalized: bool = False
    final_response_delivered: bool = False
    cleanup_started: bool = False
    cleanup_completed: bool = False
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    final_assessment: Optional[Dict[str, Any]] = None
    idempotent_event_ids: List[str] = field(default_factory=list)

    def record_off_topic_violation(self) -> int:
        """Increments off-topic counter and updates warning level."""
        self.off_topic_count += 1
        self.warning_level = min(3, self.off_topic_count)
        if self.off_topic_count >= 3:
            self.terminate_session("REPEATED_OFF_TOPIC_INTERACTIONS")
        return self.off_topic_count

    def terminate_session(self, reason: str) -> None:
        """Deterministically marks session as terminated with distinct terminal outcome."""
        self.session_status = "TERMINATED"
        self.stage_1_status = "TERMINATED"
        self.is_completed = True
        self.current_state = "TERMINATED"
        self.termination_reason = reason
        if reason == "TERMINATED_BY_CANDIDATE":
            self.terminal_outcome = "TERMINATED_BY_CANDIDATE"
        elif reason in ["REPEATED_OFF_TOPIC_INTERACTIONS", "PROMPT_INJECTION"]:
            self.terminal_outcome = "TERMINATED_BY_GUARDRAIL"
        elif reason == "SYSTEM_ERROR":
            self.terminal_outcome = "TERMINATED_BY_SYSTEM_ERROR"
        elif not self.terminal_outcome:
            self.terminal_outcome = "TERMINATED_BY_GUARDRAIL" if "OFF_TOPIC" in reason else "TERMINATED"
        self.finalize_assessment()

    def is_terminated(self) -> bool:
        """Returns True if session has reached a closed terminal state."""
        return self.cleanup_completed or self.session_status in ["TERMINATED", "CLOSED"]

    def finalize_assessment(self) -> Dict[str, Any]:
        """Finalizes the assessment idempotently, consolidating all questions, evaluations, and metrics."""
        if self.assessment_finalized and self.final_assessment is not None:
            return self.final_assessment

        self.completed_at = self.completed_at or time.time()
        self.assessment_finalized = True

        outcome = self.terminal_outcome or (
            "TERMINATED_BY_CANDIDATE" if self.termination_reason == "TERMINATED_BY_CANDIDATE"
            else "TERMINATED_BY_GUARDRAIL" if self.termination_reason in ["REPEATED_OFF_TOPIC_INTERACTIONS", "PROMPT_INJECTION"]
            else "TERMINATED_BY_SYSTEM_ERROR" if self.termination_reason == "SYSTEM_ERROR"
            else "COMPLETED" if self.is_completed
            else "TERMINATED"
        )
        self.terminal_outcome = outcome

        total_primary = self.primary_question_count
        answered_count = sum(1 for q in self.question_state.values() if q.get("status") in ["ANSWERED", "REVISITED_ANSWERED"])
        skipped_count = len(self.skipped_question_ids)
        revisited_count = len(self.revisited_question_ids)
        timeout_count = sum(1 for q in self.question_state.values() if q.get("status") == "UNANSWERED_TIMEOUT")

        self.final_assessment = {
            "session_id": self.session_id,
            "selected_skill": self.selected_skill or "Python",
            "selected_language": settings.GNANI_STT_LANGUAGE,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.completed_at - self.started_at, 2),
            "terminal_outcome": outcome,
            "termination_reason": self.termination_reason,
            "summary_metrics": {
                "primary_questions_asked": total_primary,
                "questions_answered": answered_count,
                "questions_skipped_permanently": skipped_count,
                "questions_revisited": revisited_count,
                "timeouts": timeout_count,
                "follow_ups_asked": len(self.follow_up_history),
                "off_topic_violations": self.off_topic_count,
            },
            "question_history": self.question_state,
            "candidate_answers": self.candidate_answers,
            "follow_up_history": self.follow_up_history,
            "concepts_mentioned": self.concepts_mentioned,
            "unclear_or_missing_concepts": self.unclear_or_missing_concepts,
        }
        return self.final_assessment

    def mark_cleanup_completed(self) -> None:
        """Marks session cleanup as completed idempotently."""
        self.cleanup_started = True
        self.cleanup_completed = True
        if self.session_status != "TERMINATED":
            self.session_status = "CLOSED"

    # Dynamic Skip and Revisit State
    skip_intent: Optional[str] = None
    skip_preference: str = "PENDING"  # PENDING, SKIP_ENTIRELY, REVISIT_AFTER_NEXT, ANSWERED, UNRESOLVED
    original_skip_request: Optional[str] = None
    candidate_clarification_response: Optional[str] = None
    clarification_retry_count: int = 0
    question_visit_mode: str = "INITIAL"  # INITIAL, REVISIT
    skipped_question_ids: List[str] = field(default_factory=list)
    revisit_queue: List[Dict[str, Any]] = field(default_factory=list)
    revisited_question_ids: List[str] = field(default_factory=list)
    q2_revisit_completed: bool = False
    q3_completed: bool = False
    current_transition_reason: Optional[str] = None

    # Stage 2 Per-Question State Contract & FIFO Revisit Queue Tracking
    # question_state mapping: question_id -> { status, primary_slot_consumed, revisit_allowed, revisit_used, revisit_count, original_response, revisit_response, evaluation, clarification_count }
    question_state: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_question_stage: str = "STAGE_2_PRIMARY"  # STAGE_2_PRIMARY, STAGE_2_REVISIT, STAGE_2_COMPLETE
    answer_timer_duration: float = 30.0
    answer_capture_state: str = "WAITING_FOR_ANSWER"  # WAITING_FOR_ANSWER, ANSWER_CAPTURE_IN_PROGRESS, ANSWER_RECEIVED

    def record_turn(self, speaker: str, text: str, question_id: Optional[str] = None) -> None:
        """Appends a spoken turn to the full session conversation transcript."""
        if not text:
            return
        self.conversation_turns.append({
            "turn": len(self.conversation_turns) + 1,
            "speaker": speaker,
            "text": text,
            "question_id": question_id or self.current_question_id,
            "timestamp": time.time(),
        })

    def get_qa_context_summary(self, max_items: int = 6) -> str:
        """Builds compact iterative Q&A + follow-up context for next-question prompt generation."""
        if not self.candidate_answers and not self.follow_up_history:
            return "None"
        lines: List[str] = []
        for idx, ans in enumerate(self.candidate_answers[-max_items:], 1):
            q_txt = (ans.get("question_text") or "")[:120]
            a_txt = (ans.get("answer_text") or "")[:150]
            lines.append(f"Q{idx}: {q_txt} | A{idx}: {a_txt}")
        for f_idx, fu in enumerate(self.follow_up_history[-3:], 1):
            lines.append(f"FollowUp{f_idx}: {fu.get('follow_up_question', '')[:120]}")
        return "\n".join(lines)

    def can_ask_primary_question(self) -> bool:
        """Enforces that no more than max_primary_questions can be asked."""
        return self.primary_question_count < self.max_primary_questions

    def is_last_primary_question(self) -> bool:
        """Returns True when the universal countdown reaches 1 (current question is the last one)."""
        return self.remaining_questions <= 1

    def can_ask_follow_up(self) -> bool:
        """Enforces that maximum 1 follow-up can be asked per primary question (including Q3; revisits excluded)."""
        if self.question_visit_mode == "REVISIT":
            return False
        return self.follow_up_count_for_current_question < self.max_follow_ups_per_question

    def record_primary_question(self, question_id: str, question_text: str, topic: str = "", expected_concepts: Optional[List[str]] = None) -> None:
        """Records presentation of a new primary question and updates the universal countdown."""
        self.primary_question_count += 1
        self.remaining_questions = max(1, self.max_primary_questions - self.primary_question_count + 1)
        self.current_question_id = question_id
        self.current_question_text = question_text
        self.current_question_topic = topic
        self.current_expected_concepts = expected_concepts or []
        self.presented_questions.append(question_id)
        # Reset follow-up counter for the new primary question
        self.follow_up_count_for_current_question = 0
        self.answer_capture_state = "WAITING_FOR_ANSWER"

        # Initialize or update per-question tracking
        if question_id not in self.question_state:
            self.question_state[question_id] = {
                "question_id": question_id,
                "question_text": question_text,
                "topic": topic,
                "expected_concepts": expected_concepts or [],
                "status": "PENDING",
                "primary_slot_consumed": True,
                "revisit_allowed": True,
                "revisit_used": False,
                "revisit_count": 0,
                "clarification_count": 0,
                "original_response": None,
                "revisit_response": None,
                "evaluation": None,
            }

    def record_follow_up(self, question_id: str, question_text: str, follow_up_text: str, candidate_answer: str) -> None:
        """Records presentation of a follow-up."""
        self.follow_up_count_for_current_question += 1
        self.follow_up_history.append({
            "primary_question_id": question_id,
            "primary_question": question_text,
            "candidate_answer": candidate_answer,
            "follow_up_question": follow_up_text,
        })
        self.current_question_text = follow_up_text
        self.answer_capture_state = "WAITING_FOR_ANSWER"

    def record_answer(self, question_id: str, question_text: str, answer_text: str, concepts_identified: List[str], missing_concepts: List[str]) -> None:
        """Stores candidate answer into session memory and per-question state."""
        self.candidate_answers.append({
            "question_id": question_id,
            "question_text": question_text,
            "answer_text": answer_text,
            "concepts_identified": concepts_identified,
            "missing_concepts": missing_concepts,
            "timestamp": time.time(),
        })
        for c in concepts_identified:
            if c not in self.concepts_mentioned:
                self.concepts_mentioned.append(c)
        self.unclear_or_missing_concepts = [c for c in missing_concepts if c not in self.concepts_mentioned]

        # Update per-question state
        if question_id in self.question_state:
            q_info = self.question_state[question_id]
            if self.question_visit_mode == "REVISIT":
                q_info["revisit_response"] = answer_text
                q_info["status"] = "REVISITED_ANSWERED"
            else:
                q_info["original_response"] = answer_text
                q_info["status"] = "ANSWERED"
            q_info["evaluation"] = {
                "concepts_identified": concepts_identified,
                "missing_concepts": missing_concepts,
            }

        # Update compact rolling summary
        brief_ans = answer_text[:100] + "..." if len(answer_text) > 100 else answer_text
        self.rolling_summary += f" Q: {question_text[:50]}... A: {brief_ans};"
        self.answer_capture_state = "ANSWER_RECEIVED"

    def queue_for_revisit(self, question_id: str, question_text: str, topic: str = "", expected_concepts: Optional[List[str]] = None) -> bool:
        """Queues a question to be revisited after all primary questions are completed (FIFO order).
        
        Enforces per-question revisit allowance: each primary question gets exactly 1 revisit opportunity.
        Returns True if enqueued, False if revisit allowance was already used or question is permanently skipped.
        """
        # Deterministic check: cannot revisit if permanently skipped
        if question_id in self.skipped_question_ids:
            return False

        q_info = self.question_state.get(question_id)
        if q_info:
            if q_info.get("revisit_used") or q_info.get("revisit_count", 0) >= 1 or not q_info.get("revisit_allowed", True):
                return False

        item = {
            "id": question_id,
            "question_text": question_text,
            "topic": topic,
            "expected_concepts": expected_concepts or []
        }
        # Prevent duplicate queuing (FIFO integrity)
        if not any(q["id"] == question_id for q in self.revisit_queue):
            self.revisit_queue.append(item)
            if q_info:
                q_info["status"] = "SKIPPED_PENDING_REVISIT"
                q_info["primary_slot_consumed"] = True

        self.skip_preference = "REVISIT_AFTER_NEXT"
        return True

    def mark_permanent_skip(self, question_id: str) -> None:
        """Marks a question as permanently skipped (never to be asked again or enqueued)."""
        if question_id not in self.skipped_question_ids:
            self.skipped_question_ids.append(question_id)
        # Remove from revisit queue if it was there
        self.revisit_queue = [q for q in self.revisit_queue if q["id"] != question_id]
        if question_id in self.question_state:
            q_info = self.question_state[question_id]
            q_info["status"] = "SKIPPED_PERMANENTLY"
            q_info["revisit_allowed"] = False
            q_info["primary_slot_consumed"] = True
        self.skip_preference = "SKIP_ENTIRELY"

    def mark_timeout_unanswered(self, question_id: str) -> None:
        """Marks a question as unanswered due to answer timeout."""
        if question_id in self.question_state:
            q_info = self.question_state[question_id]
            q_info["status"] = "UNANSWERED_TIMEOUT"
            q_info["primary_slot_consumed"] = True
        self.answer_capture_state = "WAITING_FOR_ANSWER"

    def has_pending_revisit(self) -> bool:
        """Checks if there is an unvisited question queued in FIFO revisit queue."""
        return len(self.revisit_queue) > 0

    def pop_revisit(self) -> Optional[Dict[str, Any]]:
        """Pops the head (FIFO) question queued for revisit and marks revisit allowance used."""
        if self.revisit_queue:
            item = self.revisit_queue.pop(0)
            q_id = item["id"]
            if q_id in self.question_state:
                q_info = self.question_state[q_id]
                q_info["status"] = "REVISIT_IN_PROGRESS"
                q_info["revisit_used"] = True
                q_info["revisit_count"] = q_info.get("revisit_count", 0) + 1
                q_info["revisit_allowed"] = False
            return item
        return None

    def mark_revisit_completed(self, question_id: str, answered: bool = True) -> None:
        """Marks a question revisit as completed so it is never revisited again."""
        if question_id not in self.revisited_question_ids:
            self.revisited_question_ids.append(question_id)
        if question_id in self.question_state:
            q_info = self.question_state[question_id]
            q_info["status"] = "REVISITED_ANSWERED" if answered else "REVISITED_UNANSWERED"
            q_info["revisit_allowed"] = False
            q_info["revisit_used"] = True
        self.q2_revisit_completed = True
        self.skip_preference = "ANSWERED"
        self.question_visit_mode = "INITIAL"
        self.answer_capture_state = "ANSWER_RECEIVED"


class SessionManager:
    """In-memory session manager isolating sessions and clearing upon conclusion."""

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}

    def get_or_create(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[SessionState]:
        return self._sessions.get(session_id)

    def cleanup(self, session_id: str) -> None:
        if session_id in self._sessions:
            del self._sessions[session_id]

    def clear_all(self) -> None:
        self._sessions.clear()

session_manager = SessionManager()
