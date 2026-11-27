import asyncio
import logging
from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from vani.graph.state import InterviewState
from vani.graph.nodes import (
    greeting_node,
    readiness_node,
    clarification_node,
    question_delivery_node,
    answer_processing_node,
    repeat_node,
    pause_node,
    resume_node,
    skill_switch_node,
    remaining_questions_node,
    skip_node,
    ask_skip_confirmation_node,
    classify_skip_preference_node,
    ask_clarification_node,
    route_after_q3_node,
    example_clarification_node,
    correction_node,
    recovery_node,
    conclusion_node,
    next_question_node,
    voluntary_termination_node,
)
from vani.session.manager import session_manager
from vani.guardrails.engine import guardrails
from config.settings import settings

logger = logging.getLogger("vani.graph.workflow")

# Entry node for dispatching conversational turns
async def dispatch_turn_node(state: InterviewState) -> Dict[str, Any]:
    """Authoritative entry node that prepares turn state from the session manager."""
    session_id = state.get("session_id", "default")
    session = session_manager.get_or_create(session_id)
    
    utterance = (state.get("candidate_utterance") or "").strip()
    return {
        "session_id": session_id,
        "current_state": session.current_state,
        "selected_skill": session.selected_skill,
        "primary_question_count": session.primary_question_count,
        "max_primary_questions": session.max_primary_questions,
        "current_question_id": session.current_question_id,
        "is_paused": session.is_paused,
        "is_completed": session.is_completed,
        "candidate_utterance": utterance,
    }

# Routing function from entry dispatch
def route_dispatch(state: InterviewState) -> str:
    """Routes conversational turn to the corresponding stage node."""
    curr = state.get("current_state", "GREETING")
    utterance = (state.get("candidate_utterance") or "").strip()

    # If session is paused, route to answer_processing for pause/resume handling
    if state.get("is_paused"):
        return "answer_processing"

    # If in CONCLUSION state, route to conclusion node
    if curr == "CONCLUSION":
        return "conclusion"

    # Terminal state check
    if curr in ["COMPLETED", "TERMINATED", "CLOSED"] or state.get("is_completed"):
        if curr == "CONCLUSION":
            return "conclusion"
        return END

    # If primary questions have already started, route to answer_processing (or skip preference classification)
    if state.get("primary_question_count", 0) > 0 and curr not in ["COMPLETED", "TERMINATED", "CLOSED"]:
        if curr == "SKIP_CONFIRMATION":
            return "classify_skip_preference"
        return "answer_processing"

    if curr == "GREETING" and not utterance:
        return "greeting"
    elif curr in ["GREETING", "READINESS_CHECK", "INITIALIZATION", "AWAITING_CANDIDATE", "PREPARATION_WAIT", "READINESS_CONFIRMATION"]:
        return "readiness"

    return END

def route_after_readiness(state: InterviewState) -> str:
    """Routes after candidate readiness check."""
    curr = state.get("current_state", "")
    if state.get("agent_response"):
        return END
    if curr == "LISTENING" and state.get("current_question_text"):
        return "question_delivery"
    if curr == "CLARIFICATION":
        return "clarification"
    if curr == "PAUSED":
        return "pause"
    if curr == "TERMINATED":
        return "voluntary_termination"
    return END

def route_after_skip_classification(state: InterviewState) -> str:
    """Routes after candidate clarifies their skip preference."""
    if state.get("agent_response"):
        return END
    pref = state.get("skip_preference")
    retry = state.get("clarification_retry_count", 0)
    if pref == "UNCLEAR" and retry <= 1:
        return "ask_clarification"
    if state.get("current_state") == "ROUTE_AFTER_Q3":
        return "route_after_q3"
    return "question_delivery"

def route_after_answer(state: InterviewState) -> str:
    """Routes after evaluating candidate answer."""
    if state.get("agent_response"):
        return END
    if state.get("termination_reason") == "TERMINATED_BY_CANDIDATE":
        return "voluntary_termination"
    if state.get("current_state") == "TERMINATED" or state.get("termination_reason"):
        return END
    if state.get("is_completed"):
        return "conclusion"
    if state.get("is_paused"):
        return "pause"
    if state.get("current_state") == "ROUTE_AFTER_Q3":
        return "route_after_q3"
    if state.get("current_state") == "SKIP_CONFIRMATION":
        return "skip"
    if state.get("current_question_text"):
        return "question_delivery"
    return END

def route_after_q3(state: InterviewState) -> str:
    """Routes after primary Q3 is completed (checks pending revisits)."""
    if state.get("revisit_queue") and not state.get("q2_revisit_completed"):
        return "question_delivery"
    return "conclusion"


def _stop_if_responded(next_node: str):
    """Returns END once a node has produced agent_response; otherwise documents flowchart transition."""
    def _router(state: InterviewState) -> str:
        if state.get("agent_response"):
            return END
        return next_node
    return _router


def create_interview_graph() -> StateGraph:
    """Builds the authoritative LangGraph StateGraph for VANI 2.0 as a vertical top-down flowchart."""
    graph = StateGraph(InterviewState)

    # 1. Register workflow nodes (no skill_selection; skill is supplied at session init)
    graph.add_node("dispatch_turn", dispatch_turn_node)
    graph.add_node("greeting", greeting_node)
    graph.add_node("readiness", readiness_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("question_delivery", question_delivery_node)
    graph.add_node("answer_processing", answer_processing_node)
    graph.add_node("repeat", repeat_node)
    graph.add_node("pause", pause_node)
    graph.add_node("resume", resume_node)
    graph.add_node("skill_switch", skill_switch_node)
    graph.add_node("remaining_questions", remaining_questions_node)
    graph.add_node("skip", skip_node)
    graph.add_node("ask_skip_confirmation", ask_skip_confirmation_node)
    graph.add_node("classify_skip_preference", classify_skip_preference_node)
    graph.add_node("ask_clarification", ask_clarification_node)
    graph.add_node("route_after_q3", route_after_q3_node)
    graph.add_node("example_clarification", example_clarification_node)
    graph.add_node("correction", correction_node)
    graph.add_node("recovery", recovery_node)
    graph.add_node("conclusion", conclusion_node)
    graph.add_node("voluntary_termination", voluntary_termination_node)

    # 2. Top-Down Entry Dispatcher (Stage Entry Points)
    graph.add_edge(START, "dispatch_turn")
    graph.add_conditional_edges(
        "dispatch_turn",
        route_dispatch,
        {
            "greeting": "greeting",
            "readiness": "readiness",
            "answer_processing": "answer_processing",
            "classify_skip_preference": "classify_skip_preference",
            "conclusion": "conclusion",
            "voluntary_termination": "voluntary_termination",
            END: END,
        },
    )

    # 3. Stage 1: Greeting -> Readiness -> Clarification / Question Delivery
    graph.add_conditional_edges(
        "greeting",
        _stop_if_responded("readiness"),
        {"readiness": "readiness", END: END},
    )
    graph.add_conditional_edges(
        "readiness",
        route_after_readiness,
        {
            "clarification": "clarification",
            "question_delivery": "question_delivery",
            "pause": "pause",
            "voluntary_termination": "voluntary_termination",
            END: END,
        },
    )
    graph.add_edge("clarification", END)

    # 4. Stage 2: Question Delivery -> Answer Processing
    graph.add_conditional_edges(
        "question_delivery",
        _stop_if_responded("answer_processing"),
        {"answer_processing": "answer_processing", END: END},
    )

    graph.add_conditional_edges(
        "answer_processing",
        route_after_answer,
        {
            "repeat": "repeat",
            "example_clarification": "example_clarification",
            "remaining_questions": "remaining_questions",
            "correction": "correction",
            "skill_switch": "skill_switch",
            "recovery": "recovery",
            "pause": "pause",
            "skip": "skip",
            "question_delivery": "question_delivery",
            "route_after_q3": "route_after_q3",
            "conclusion": "conclusion",
            "voluntary_termination": "voluntary_termination",
            END: END,
        },
    )

    # 5. Pause -> Resume Sub-Flow
    graph.add_conditional_edges(
        "pause",
        _stop_if_responded("resume"),
        {"resume": "resume", END: END},
    )
    graph.add_edge("resume", END)

    # 6. Skip & FIFO Revisit Sub-Flow
    graph.add_edge("skip", "ask_skip_confirmation")
    graph.add_conditional_edges(
        "ask_skip_confirmation",
        _stop_if_responded("classify_skip_preference"),
        {"classify_skip_preference": "classify_skip_preference", END: END},
    )
    graph.add_conditional_edges(
        "classify_skip_preference",
        route_after_skip_classification,
        {
            "ask_clarification": "ask_clarification",
            "question_delivery": "question_delivery",
            "route_after_q3": "route_after_q3",
            END: END,
        },
    )
    graph.add_edge("ask_clarification", END)

    # 7. Stage 3: Post-Q3 Revisit Check -> Conclusion -> END
    graph.add_conditional_edges(
        "route_after_q3",
        route_after_q3,
        {
            "question_delivery": "question_delivery",
            "conclusion": "conclusion",
        },
    )
    graph.add_conditional_edges(
        "voluntary_termination",
        _stop_if_responded("conclusion"),
        {"conclusion": "conclusion", END: END},
    )
    graph.add_edge("conclusion", END)

    # 8. In-Turn Helpers
    graph.add_edge("repeat", END)
    graph.add_edge("example_clarification", END)
    graph.add_edge("remaining_questions", END)
    graph.add_edge("correction", END)
    graph.add_edge("skill_switch", END)
    graph.add_edge("recovery", END)

    return graph


def compile_interview_graph(custom_checkpointer: Optional[Any] = None) -> Any:
    """Compiles the VANI 2.0 StateGraph with an optional LangGraph checkpointer."""
    workflow = create_interview_graph()
    if custom_checkpointer is not None:
        return workflow.compile(checkpointer=custom_checkpointer)
    return workflow.compile()


# Compiled authoritative interview graph with memory checkpointer
checkpointer = MemorySaver()
interview_graph = compile_interview_graph(custom_checkpointer=checkpointer)


class InterviewEngine:
    """Session-aware interviewer orchestrator that drives LangGraph turns with per-session locking and recovery."""

    def __init__(self) -> None:
        self.graph = interview_graph
        self._session_locks: Dict[str, asyncio.Lock] = {}

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Returns a per-session asyncio.Lock to serialize concurrent turns and timeouts."""
        if not session_id or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def cleanup_session_thread(self, session_id: str) -> None:
        """Releases in-memory lock and checkpointer state for a concluded session."""
        self._session_locks.pop(session_id, None)
        if hasattr(checkpointer, "delete_thread"):
            try:
                checkpointer.delete_thread(session_id)
            except Exception as exc:
                logger.debug("Checkpointer cleanup skipped for %s: %s", session_id, exc)

    async def start_interview(self, session_id: str) -> str:
        """Phase 1: Initiates a new session and returns the spoken greeting through LangGraph."""
        async with self._get_session_lock(session_id):
            session = session_manager.get_or_create(session_id)

            # Prevent duplicate greeting only if questions have already started
            if session.greeting_completed and session.last_agent_utterance and len(session.candidate_answers) > 0:
                return session.last_agent_utterance

            session.current_state = "GREETING"

            initial_state: InterviewState = {
                "session_id": session_id,
                "current_state": "GREETING",
                "selected_skill": session.selected_skill,
                "primary_question_count": 0,
                "max_primary_questions": session.max_primary_questions,
                "follow_up_count_for_current_question": 0,
                "max_follow_ups_per_question": session.max_follow_ups_per_question,
                "presented_questions": [],
                "candidate_answers": [],
                "concepts_mentioned": [],
                "unclear_or_missing_concepts": [],
                "follow_up_history": [],
                "is_paused": False,
                "is_completed": False,
                "stage_1_status": "NOT_STARTED",
                "greeting_completed": False,
                "off_topic_count": session.off_topic_count,
                "warning_level": session.warning_level,
                "readiness_status": "PENDING",
                "session_status": "ACTIVE",
            }

            config = {"configurable": {"thread_id": session_id}}
            try:
                result = await self.graph.ainvoke(initial_state, config=config)
                session.current_state = result.get("current_state", "AWAITING_CANDIDATE")
                response = result.get("agent_response", "Hello! Welcome to your interview. I'm Vani, your AI interviewer. How are you doing today?")
            except Exception as exc:
                logger.exception("Error starting interview for session %s: %s", session_id, exc)
                response = "Hello! Welcome to your interview. I'm Vani, your AI interviewer. How are you doing today?"
                session.current_state = "AWAITING_CANDIDATE"

            enforced = guardrails.enforce_output_length(response)
            session.last_agent_utterance = enforced
            session.greeting_completed = True
            return enforced

    async def handle_preparation_timeout(self, session_id: str) -> str:
        """UC: Preparation timeout (20s) expires; prompt for readiness confirmation."""
        async with self._get_session_lock(session_id):
            session = session_manager.get_or_create(session_id)
            if session.is_terminated():
                return ""
            if session.current_state == "PREPARATION_WAIT":
                session.current_state = "READINESS_CONFIRMATION"
                response = "Are you ready to proceed with your interview?"
                session.last_agent_utterance = response
                return response
            return ""

    async def handle_confirmation_timeout(self, session_id: str) -> str:
        """UC: Confirmation timeout expires; politely terminate the session."""
        async with self._get_session_lock(session_id):
            session = session_manager.get_or_create(session_id)
            if session.is_terminated():
                return ""
            session.terminate_session("CONFIRMATION_TIMEOUT")
            response = "That's alright. We'll close this session for now. You can take some time and try again later."
            session.last_agent_utterance = response
            self.cleanup_session_thread(session_id)
            return response

    async def handle_answer_timeout(self, session_id: str) -> str:
        """Section 8 Answer Timeout: 30-second candidate answer window expires with no response."""
        async with self._get_session_lock(session_id):
            session = session_manager.get_or_create(session_id)
            if session.is_terminated():
                return ""

            # Race condition handling: if candidate speech capture is in progress or already received, do not timeout
            if session.answer_capture_state in ["ANSWER_CAPTURE_IN_PROGRESS", "ANSWER_RECEIVED"]:
                return ""

            active_q_id = session.current_question_id or "unknown"
            session.mark_timeout_unanswered(active_q_id)

            timeout_msg = "I understand you weren't able to provide an answer within the allotted time. Let's move on to the next question."

            state_input: InterviewState = {
                "session_id": session_id,
                "candidate_utterance": "",
                "current_state": session.current_state,
            }
            next_step = await next_question_node(state_input)
            response = guardrails.enforce_output_length(
                f"{timeout_msg} {next_step.get('agent_response', '')}".strip()
            )
            session.last_agent_utterance = response
            return response

    async def handle_candidate_utterance(self, session_id: str, utterance: str) -> str:
        """Processes a spoken candidate turn purely through the authoritative LangGraph."""
        async with self._get_session_lock(session_id):
            session = session_manager.get_or_create(session_id)

            # If already terminated or completed (outside CONCLUSION inquiry window), reject further candidate turns
            if session.is_terminated() or (session.is_completed and session.current_state != "CONCLUSION"):
                return "This interview session has already closed and concluded. Thank you for your time."

            clean_input = (utterance or "").strip()
            if not clean_input:
                if session.current_state == "CONCLUSION":
                    return session.last_agent_utterance or "Your interview has completed. Thank you for your time."
                # Silence handling (UC28)
                rec = await recovery_node({"session_id": session_id})
                return rec.get("agent_response", "I didn't hear anything. Could you please answer?")

            # G01: Prompt injection check (remain in current state and redirect safely)
            is_safe, injection_msg = guardrails.check_prompt_injection(clean_input)
            if not is_safe:
                session.last_agent_utterance = injection_msg
                return injection_msg

            state_input: InterviewState = {
                "session_id": session_id,
                "candidate_utterance": clean_input,
                "current_state": session.current_state,
                "selected_skill": session.selected_skill,
                "current_question_id": session.current_question_id,
                "current_question_text": session.current_question_text,
                "current_question_topic": session.current_question_topic,
                "current_expected_concepts": session.current_expected_concepts,
                "primary_question_count": session.primary_question_count,
                "max_primary_questions": session.max_primary_questions,
                "follow_up_count_for_current_question": session.follow_up_count_for_current_question,
                "max_follow_ups_per_question": session.max_follow_ups_per_question,
                "presented_questions": session.presented_questions,
                "candidate_answers": session.candidate_answers,
                "concepts_mentioned": session.concepts_mentioned,
                "unclear_or_missing_concepts": session.unclear_or_missing_concepts,
                "follow_up_history": session.follow_up_history,
                "is_paused": session.is_paused,
                "is_completed": session.is_completed,
                "revisit_queue": session.revisit_queue,
                "skipped_question_ids": session.skipped_question_ids,
                "revisited_question_ids": session.revisited_question_ids,
                "q2_revisit_completed": session.q2_revisit_completed,
                "q3_completed": session.q3_completed,
                "question_visit_mode": session.question_visit_mode,
                "stage_1_status": session.stage_1_status,
                "greeting_completed": session.greeting_completed,
                "off_topic_count": session.off_topic_count,
                "warning_level": session.warning_level,
                "readiness_status": session.readiness_status,
                "wait_reason": session.wait_reason,
                "wait_started_at": session.wait_started_at,
                "readiness_confirmation_count": session.readiness_confirmation_count,
                "clarification_count": session.clarification_count,
                "session_status": session.session_status,
                "termination_reason": session.termination_reason,
            }

            config = {"configurable": {"thread_id": session_id}}
            try:
                result = await self.graph.ainvoke(state_input, config=config)
                session.current_state = result.get("current_state", session.current_state)
                if "is_paused" in result:
                    session.is_paused = bool(result["is_paused"])
                if "is_completed" in result and result["is_completed"]:
                    session.is_completed = True
                response = result.get("agent_response", "Thank you. Let us proceed.")
            except Exception as exc:
                logger.exception("LangGraph turn error in session %s: %s", session_id, exc)
                rec = await recovery_node({"session_id": session_id})
                response = rec.get("agent_response", "I did not quite catch that. Could you please repeat or elaborate on your answer?")

            enforced = guardrails.enforce_output_length(response)
            session.last_agent_utterance = enforced
            if session.is_terminated():
                self.cleanup_session_thread(session_id)
            return enforced

interview_engine = InterviewEngine()
