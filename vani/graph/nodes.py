import time
import logging
from typing import Dict, Any, Optional
from vani.graph.state import InterviewState
from vani.session.manager import session_manager
from vani.mcp.client import mcp_client
from vani.llm.model import model_service
from vani.llm.question_generator import question_generator, QuestionValidator
from vani.llm.prompt_builder import prompt_builder
from vani.llm.prompts import SYSTEM_INTERVIEWER_INSTRUCTION, UNIFIED_EVALUATION_AND_QUESTION_PROMPT
from vani.guardrails.engine import guardrails, MSG_POLITE_TERMINATE
from config.settings import settings

logger = logging.getLogger("vani.graph.nodes")

PAUSE_PHRASES = (
    "please pause", "pause interview", "pause", "hold on",
    "wait a minute", "give me a moment", "brb", "one second",
)
RESUME_PHRASES = ("please resume", "resume interview", "resume", "i am back", "continue", "ready now")
VOLUNTARY_TERMINATION_PHRASES = (
    "want to stop", "stop the interview", "stop interview", "end this session",
    "end the session", "don't want to continue", "dont want to continue",
    "terminate the interview", "terminate interview", "quit the interview",
    "quit interview", "please end this session", "i don't want to continue",
    "i dont want to continue",
)
PHASE1_REFUSAL_PHRASES = (
    "don't want to continue", "dont want to continue",
    "i don't want to continue", "i dont want to continue",
)


def _matches_any(lowered_text: str, phrases: tuple[str, ...]) -> bool:
    """Returns True if any phrase appears in lowered_text."""
    return any(p in lowered_text for p in phrases)


async def _deliver_first_question(session: Any, skill: str, intro_prefix: str) -> Optional[Dict[str, Any]]:
    """Selects skill via MCP, fetches DB few-shot prompt & generates Q1 via LLM, and builds state update."""
    mcp_client.select_interview_skill(session.session_id, skill)
    session.selected_skill = skill
    q_res = await mcp_client.aget_next_question(
        session.session_id,
        skill,
        sub_skill=session.selected_sub_skill,
    )
    if q_res.get("status") != "success":
        return None
    q_data = q_res["question"]
    session.record_primary_question(
        question_id=q_data["id"],
        question_text=q_data["question_text"],
        topic=q_data["topic"],
        expected_concepts=q_data["expected_concepts"],
    )
    response = f"{intro_prefix}{q_data['question_text']}"
    session.last_agent_utterance = response
    session.current_state = "LISTENING"
    return {
        "selected_skill": skill,
        "current_question_id": q_data["id"],
        "current_question_text": q_data["question_text"],
        "current_question_topic": q_data["topic"],
        "current_expected_concepts": q_data["expected_concepts"],
        "primary_question_count": session.primary_question_count,
        "follow_up_count_for_current_question": 0,
        "current_state": "LISTENING",
        "agent_response": response,
    }


def _finalize_completed_session(session: Any, response: str) -> Dict[str, Any]:
    """Marks a session COMPLETED, finalizes assessment, and cleans up in-memory context."""
    session.terminal_outcome = "COMPLETED"
    session.current_state = "COMPLETED"
    session.session_status = "COMPLETED"
    session.finalize_assessment()
    session.mark_cleanup_completed()
    session.last_agent_utterance = response
    return {
        "current_state": "COMPLETED",
        "session_status": "COMPLETED",
        "terminal_outcome": "COMPLETED",
        "is_completed": True,
        "cleanup_completed": True,
        "agent_response": response,
    }

async def greeting_node(state: InterviewState) -> Dict[str, Any]:
    """Phase 1 - Step 2: Vani natural greeting and onboarding opening."""
    session = session_manager.get_or_create(state["session_id"])
    
    # Prevent duplicate greeting only if questions have already started
    if session.greeting_completed and session.last_agent_utterance and len(session.candidate_answers) > 0:
        return {
            "current_state": session.current_state,
            "agent_response": session.last_agent_utterance,
            "greeting_completed": True,
            "stage_1_status": session.stage_1_status,
        }

    skill = session.selected_skill or "Python"
    session.selected_skill = skill
    skill_label = f"{skill} ({session.selected_sub_skill})" if session.selected_sub_skill else skill
    response = f"Hello! Welcome to your {skill_label} interview. I'm Vani, your AI interviewer. How are you doing today?"
    session.greeting_completed = True
    session.stage_1_status = "IN_PROGRESS"
    session.current_state = "AWAITING_CANDIDATE"
    session.last_agent_utterance = response
    
    return {
        "current_state": "AWAITING_CANDIDATE",
        "agent_response": response,
        "is_paused": False,
        "is_completed": False,
        "greeting_completed": True,
        "stage_1_status": "IN_PROGRESS",
    }

async def polite_termination_node(
    state: InterviewState,
    message: Optional[str] = None,
    reason: str = "POLITE_TERMINATION"
) -> Dict[str, Any]:
    """Handles polite session termination with LiveKit cleanup preparation."""
    session = session_manager.get_or_create(state["session_id"])
    session.terminate_session(reason)
    response = message or MSG_POLITE_TERMINATE
    session.last_agent_utterance = response
    return {
        "is_completed": True,
        "session_status": "TERMINATED",
        "stage_1_status": "TERMINATED",
        "termination_reason": reason,
        "current_state": "TERMINATED",
        "agent_response": response,
    }

async def readiness_node(state: InterviewState) -> Dict[str, Any]:
    """Phase 1 - Step 3 & Step 4: Candidate response handling, nervousness, time requests, and universal off-topic."""
    session = session_manager.get_or_create(state["session_id"])
    utterance = (state.get("candidate_utterance") or "").strip()

    # 1. If already terminated, reject any further input
    if session.is_terminated():
        return await polite_termination_node(
            state,
            message=session.last_agent_utterance or MSG_POLITE_TERMINATE,
            reason=session.termination_reason or "SESSION_TERMINATED"
        )

    # 2. Check prompt injection guardrail
    is_safe, injection_msg = guardrails.check_prompt_injection(utterance)
    if not is_safe:
        return {"agent_response": injection_msg, "current_state": session.current_state}

    lowered = utterance.lower()
    if _matches_any(lowered, ("please pause", "pause interview", "pause")):
        return await pause_node(state)
    if _matches_any(lowered, ("please resume", "resume interview", "resume")):
        return await resume_node(state)

    # Phase 1 candidate refusal -> polite termination with MSG_POLITE_TERMINATE
    if _matches_any(lowered, PHASE1_REFUSAL_PHRASES):
        return await polite_termination_node(state, message=MSG_POLITE_TERMINATE, reason="CANDIDATE_REFUSAL")

    # Section 7: Voluntary candidate termination check
    if _matches_any(lowered, VOLUNTARY_TERMINATION_PHRASES):
        return await voluntary_termination_node(state)

    # 3. Classify intent with context
    res = await model_service.classify_phase1_intent(
        candidate_utterance=utterance,
        current_node=session.current_state,
        last_agent_utterance=session.last_agent_utterance,
        readiness_status=session.readiness_status,
        clarification_count=session.clarification_count,
    )
    intent = res.get("intent", "UNCLEAR")
    logger.info(f"Phase 1 candidate turn: '{utterance}' -> intent: {intent}")

    # 4. Universal Policy & Off-Topic Validation across all stages
    policy_decision = guardrails.handle_candidate_policy(
        session=session,
        candidate_intent=intent,
        current_stage="PHASE_1",
        current_node=session.current_state,
        utterance=utterance,
    )
    if policy_decision.action == "REDIRECT":
        session.last_agent_utterance = policy_decision.message
        return {"agent_response": policy_decision.message, "current_state": session.current_state}
    elif policy_decision.action == "WARN":
        session.last_agent_utterance = policy_decision.message
        return {"agent_response": policy_decision.message, "current_state": session.current_state}
    elif policy_decision.action == "TERMINATE":
        return await polite_termination_node(state, message=policy_decision.message, reason="REPEATED_OFF_TOPIC_INTERACTIONS")

    # 5. Process Legitimate Phase 1 Intents
    if intent == "SOCIAL_RESPONSE":
        skill = session.selected_skill or "Python"
        response = (
            f"Glad to hear that! Today's interview consists of three technical questions on {skill} fundamentals. "
            "Whenever you are ready, let me know and we can begin."
        )
        session.current_state = "AWAITING_CANDIDATE"
        session.last_agent_utterance = response
        return {"agent_response": response, "current_state": "AWAITING_CANDIDATE"}

    elif intent == "NERVOUSNESS":
        response = "That's completely fine. Take your time. I'll give you a few moments to get comfortable."
        session.readiness_status = "PENDING"
        session.wait_reason = "NERVOUSNESS"
        session.wait_started_at = time.time()
        session.current_state = "PREPARATION_WAIT"
        session.last_agent_utterance = response
        return {
            "agent_response": response,
            "current_state": "PREPARATION_WAIT",
            "readiness_status": "PENDING",
            "wait_reason": "NERVOUSNESS",
            "wait_started_at": session.wait_started_at,
        }

    elif intent == "REQUEST_TIME":
        response = "Of course. Take a moment. I'll wait for you."
        session.readiness_status = "PENDING"
        session.wait_reason = "REQUEST_TIME"
        session.wait_started_at = time.time()
        session.current_state = "PREPARATION_WAIT"
        session.last_agent_utterance = response
        return {
            "agent_response": response,
            "current_state": "PREPARATION_WAIT",
            "readiness_status": "PENDING",
            "wait_reason": "REQUEST_TIME",
            "wait_started_at": session.wait_started_at,
        }

    elif intent == "VANI_QUESTION":
        response = (
            "I am Vani, an AI technical interviewer built to conduct conversational technical interviews. "
            "Today we will cover core Python fundamentals for beginners. Are you ready to begin?"
        )
        session.current_state = "AWAITING_CANDIDATE"
        session.last_agent_utterance = response
        return {"agent_response": response, "current_state": "AWAITING_CANDIDATE"}

    elif intent == "PROCESS_QUESTION":
        response = (
            "The interview consists of three primary technical questions with brief follow-ups. "
            "You can answer naturally by voice, ask me to repeat a question, or pause whenever you need. "
            "Whenever you are ready, let me know and we will get started!"
        )
        session.current_state = "AWAITING_CANDIDATE"
        session.last_agent_utterance = response
        return {"agent_response": response, "current_state": "AWAITING_CANDIDATE"}

    elif intent in ["READY", "READY_CONFIRMATION"]:
        # Candidate confirmed readiness -> Transition to Phase 2!
        skill = session.selected_skill or "Python"
        session.stage_1_status = "READY_FOR_PHASE_2"
        session.readiness_status = "READY"
        session.current_state = "ASKING_QUESTION"

        intro = f"Wonderful! Today's interview consists of three foundational {skill} questions with follow-ups. Question one: "
        delivered = await _deliver_first_question(session, skill, intro)
        if delivered is not None:
            delivered["stage_1_status"] = "READY_FOR_PHASE_2"
            delivered["readiness_status"] = "READY"
            return delivered
        return await polite_termination_node(
            state,
            message="Unable to retrieve interview questions. Concluding session.",
            reason="MCP_ERROR"
        )

    elif intent in ["NOT_READY", "NOT_READY_CONFIRMATION"]:
        return await polite_termination_node(state, message=MSG_POLITE_TERMINATE, reason="CANDIDATE_REFUSAL")

    elif intent == "CLARIFICATION":
        response = (
            "This interview is designed to evaluate your understanding of Python fundamentals through three core questions. "
            "You can answer naturally by voice, ask to repeat questions, or pause at any point. "
            "Whenever you are ready, please say 'ready' to start!"
        )
        session.current_state = "AWAITING_CANDIDATE"
        session.last_agent_utterance = response
        return {"agent_response": response, "current_state": "AWAITING_CANDIDATE"}

    elif intent == "UNCLEAR":
        if session.clarification_count < 1:
            session.clarification_count += 1
            response = "Just to confirm, would you like to proceed with your interview now?"
            session.current_state = "AWAITING_CANDIDATE"
            session.last_agent_utterance = response
            return {"agent_response": response, "current_state": "AWAITING_CANDIDATE"}
        else:
            return await polite_termination_node(state, message=MSG_POLITE_TERMINATE, reason="CONFIRMATION_TIMEOUT")

    else:
        # NO_INPUT
        response = "I didn't quite catch that. Whenever you are ready to begin, please let me know!"
        session.last_agent_utterance = response
        return {"agent_response": response, "current_state": session.current_state}

async def clarification_node(state: InterviewState) -> Dict[str, Any]:
    """UC04, UC20: Candidate clarification handling."""
    session = session_manager.get_or_create(state["session_id"])
    
    response = (
        "This interview is designed to evaluate your understanding of Python fundamentals through three core questions. "
        "You can answer naturally by voice, ask to repeat questions, or pause at any point. "
        "Whenever you are ready, please say 'ready' to start!"
    )
    session.last_agent_utterance = response
    return {"agent_response": response}

async def skill_selection_node(state: InterviewState) -> Dict[str, Any]:
    """UC06, UC07, UC08: Skill listing and selection."""
    session = session_manager.get_or_create(state["session_id"])
    utterance = state.get("candidate_utterance", "").strip()

    # Check for listing request
    if any(w in utterance.lower() for w in ["what skills", "list skills", "options", "available"]):
        skills_res = mcp_client.list_available_skills()
        names = [s["name"] for s in skills_res.get("skills", [])]
        response = f"The available skills are: {', '.join(names)}. Which one would you prefer?"
        return {"agent_response": response, "current_state": "SKILL_SELECTION"}

    # Detect skill from utterance
    selected = None
    for skill in settings.SUPPORTED_SKILLS:
        if skill.lower() in utterance.lower():
            selected = skill
            break

    if not selected:
        # Check LLM extraction if candidate formulated it indirectly
        analysis = await model_service.invoke_json(
            f"The candidate was asked to choose a technical skill. Utterance: '{utterance}'. Supported: {settings.SUPPORTED_SKILLS}. Output JSON: {{\"skill\": \"Name or null\"}}"
        )
        cand_skill = analysis.get("skill")
        if cand_skill and cand_skill.capitalize() in settings.SUPPORTED_SKILLS:
            selected = cand_skill.capitalize()

    if not selected:
        # UC08: Unsupported skill
        response = f"I didn't recognize that skill. We currently support: {', '.join(settings.SUPPORTED_SKILLS)}. Which one would you like to select?"
        return {"agent_response": response, "current_state": "SKILL_SELECTION"}

    # UC07: Valid skill selected
    session.current_state = "ASKING_QUESTION"
    delivered = await _deliver_first_question(session, selected, f"Great, let's begin your {selected} interview. Question one: ")
    if delivered is not None:
        return delivered
    return {"current_state": "CONCLUSION", "agent_response": "Unable to retrieve questions. Concluding interview."}

async def question_delivery_node(state: InterviewState) -> Dict[str, Any]:
    """UC11, UC12: Retrieves and delivers primary technical question."""
    session = session_manager.get_or_create(state["session_id"])
    
    # Deterministic limit check
    if not session.can_ask_primary_question():
        return await conclusion_node(state)

    q_res = await mcp_client.aget_next_question(
        session.session_id,
        session.selected_skill,
        sub_skill=session.selected_sub_skill,
    )
    if q_res.get("status") != "success":
        return await conclusion_node(state)

    q_data = q_res["question"]
    session.record_primary_question(
        question_id=q_data["id"],
        question_text=q_data["question_text"],
        topic=q_data["topic"],
        expected_concepts=q_data["expected_concepts"],
    )

    q_num = session.primary_question_count
    num_words = ["one", "two", "three"]
    word_num = num_words[q_num - 1] if q_num <= 3 else str(q_num)
    
    response = f"Question {word_num}: {q_data['question_text']}"
    session.last_agent_utterance = response

    return {
        "current_question_id": q_data["id"],
        "current_question_text": q_data["question_text"],
        "current_question_topic": q_data["topic"],
        "current_expected_concepts": q_data["expected_concepts"],
        "primary_question_count": session.primary_question_count,
        "follow_up_count_for_current_question": 0,
        "current_state": "LISTENING",
        "agent_response": response,
    }

async def remaining_questions_node(state: InterviewState) -> Dict[str, Any]:
    """UC31: Informs candidate how many primary questions remain and notes conditional follow-ups and revisit queue."""
    session = session_manager.get_or_create(state["session_id"])
    completed = session.primary_question_count
    remaining = max(0, session.max_primary_questions - completed)
    active_q = session.current_question_text or "our current topic"
    
    revisit_note = ""
    if session.has_pending_revisit():
        revisit_count = len(session.revisit_queue)
        revisit_note = f" You also have {revisit_count} previously skipped question{'s' if revisit_count > 1 else ''} scheduled for revisit afterward."

    response = (
        f"We have covered {completed} of {session.max_primary_questions} primary questions, "
        f"leaving {remaining} primary questions remaining.{revisit_note} Follow-ups are asked conditionally based on your answers. "
        f"Whenever you are ready, please proceed with our current question: {active_q}"
    )
    session.last_agent_utterance = response
    return {
        "agent_response": response,
        "current_state": "LISTENING",
    }

async def skip_node(state: InterviewState) -> Dict[str, Any]:
    """Routes to skip confirmation node."""
    return await ask_skip_confirmation_node(state)

async def ask_skip_confirmation_node(state: InterviewState) -> Dict[str, Any]:
    """Prompts candidate whether to skip entirely or revisit after remaining questions."""
    session = session_manager.get_or_create(state["session_id"])
    active_q_id = session.current_question_id or ""

    # Revisit policy check: if currently in REVISIT mode, question has ALREADY used its revisit opportunity!
    if session.question_visit_mode == "REVISIT":
        session.mark_revisit_completed(active_q_id, answered=False)
        response = (
            "This question has already used its revisit opportunity. "
            "We will move forward."
        )
        # Advance to next queued revisit or conclusion
        if session.has_pending_revisit():
            next_rev = await route_after_q3_node(state)
            next_rev["agent_response"] = f"{response} {next_rev.get('agent_response', '')}"
            session.last_agent_utterance = next_rev["agent_response"]
            return next_rev
        conc = await conclusion_node(state)
        conc["agent_response"] = f"{response} {conc.get('agent_response', '')}"
        session.last_agent_utterance = conc["agent_response"]
        return conc

    session.current_state = "SKIP_CONFIRMATION"
    session.skip_intent = "SKIP_REQUEST"
    session.original_skip_request = state.get("candidate_utterance", "")
    session.skip_preference = "PENDING"
    session.clarification_retry_count = 0
    
    response = "That's fine. Would you like to skip this question permanently or revisit it after the remaining questions?"
    session.last_agent_utterance = response
    return {
        "current_state": "SKIP_CONFIRMATION",
        "skip_intent": "SKIP_REQUEST",
        "skip_preference": "PENDING",
        "original_skip_request": session.original_skip_request,
        "clarification_retry_count": 0,
        "agent_response": response,
    }

async def ask_clarification_node(state: InterviewState) -> Dict[str, Any]:
    """Prompts candidate to clarify ambiguous response to skip confirmation."""
    session = session_manager.get_or_create(state["session_id"])
    session.clarification_retry_count += 1
    session.current_state = "SKIP_CONFIRMATION"
    
    response = "Could you please clarify whether you want to skip this question permanently or revisit it after the remaining questions?"
    session.last_agent_utterance = response
    return {
        "current_state": "SKIP_CONFIRMATION",
        "clarification_retry_count": session.clarification_retry_count,
        "agent_response": response,
    }

async def classify_skip_preference_node(state: InterviewState) -> Dict[str, Any]:
    """Classifies candidate preference: SKIP_ENTIRELY, REVISIT_AFTER_NEXT, or UNCLEAR."""
    session = session_manager.get_or_create(state["session_id"])
    utterance = state.get("candidate_utterance", "").strip()
    session.candidate_clarification_response = utterance
    lowered = utterance.lower()

    # Support pause during skip confirmation
    if _matches_any(lowered, PAUSE_PHRASES):
        return await pause_node(state)

    # Section 7: Voluntary candidate termination check
    if _matches_any(lowered, VOLUNTARY_TERMINATION_PHRASES):
        return await voluntary_termination_node(state)

    pref = "UNCLEAR"
    if any(w in lowered for w in ["entirely", "completely", "skip it", "drop", "permanent", "never", "don't ask"]):
        pref = "SKIP_ENTIRELY"
    elif any(w in lowered for w in ["revisit", "after next", "after q3", "come back later", "try it later", "want to try it later", "revisit later", "revisit it later", "remaining questions"]):
        pref = "REVISIT_AFTER_NEXT"
    else:
        decision = await model_service.classify_skip_preference(utterance, session.current_question_text or "")
        pref = decision.preference

    logger.info(f"Classified skip preference for session {session.session_id}: {pref}")

    if pref == "SKIP_ENTIRELY":
        session.mark_permanent_skip(session.current_question_id or "")
        session.current_state = "LISTENING"
        if session.primary_question_count >= session.max_primary_questions:
            return await route_after_q3_node(state)
        q_state = await question_delivery_node(state)
        q_state["agent_response"] = f"Alright. Let's move to the next question. {q_state.get('agent_response', '')}"
        q_state["skip_preference"] = "SKIP_ENTIRELY"
        return q_state

    elif pref == "REVISIT_AFTER_NEXT":
        session.queue_for_revisit(
            question_id=session.current_question_id or "",
            question_text=session.current_question_text or "",
            topic=session.current_question_topic or "",
            expected_concepts=session.current_expected_concepts or [],
        )
        session.current_state = "LISTENING"
        if session.primary_question_count >= session.max_primary_questions:
            return await route_after_q3_node(state)
        q_state = await question_delivery_node(state)
        q_state["agent_response"] = f"Sure. We'll come back to this question after the remaining questions. {q_state.get('agent_response', '')}"
        q_state["skip_preference"] = "REVISIT_AFTER_NEXT"
        return q_state

    else:
        # UNCLEAR
        if session.clarification_retry_count < 1:
            return await ask_clarification_node(state)
        else:
            # Retry limit reached: return control to active question
            session.clarification_retry_count = 0
            session.skip_preference = "UNRESOLVED"
            session.current_state = "LISTENING"
            active_q = session.current_question_text or "our current topic"
            response = f"Understood. Let's return to our current question: {active_q}. Whenever you are ready, please share your thoughts."
            session.last_agent_utterance = response
            return {
                "current_state": "LISTENING",
                "skip_preference": "UNRESOLVED",
                "clarification_retry_count": 0,
                "agent_response": response,
            }

async def example_clarification_node(state: InterviewState) -> Dict[str, Any]:
    """UC34: Clarifies the active question by rephrasing it concisely without examples or hints."""
    session = session_manager.get_or_create(state["session_id"])
    active_q = session.current_question_text or "the current question"
    active_q_id = session.current_question_id or ""

    # Check per-question clarification allowance (Max 1 per primary question)
    q_info = session.question_state.get(active_q_id, {})
    if q_info.get("clarification_count", 0) >= 1:
        response = (
            "I have already clarified this question. "
            "Please give it your best try, or let me know if you would like to skip it."
        )
        session.last_agent_utterance = response
        return {
            "agent_response": response,
            "current_state": "LISTENING",
        }

    # Increment clarification count
    if active_q_id in session.question_state:
        session.question_state[active_q_id]["clarification_count"] = q_info.get("clarification_count", 0) + 1

    topic = session.current_question_topic or session.selected_skill or "this concept"
    res = await model_service.invoke_json(
        prompt=(
            f"Rephrase this interview question in one short, clear sentence for the candidate. "
            f"Do NOT give any examples, hints, or answers. Question: {active_q}\n"
            'Output JSON: {"rephrased": "..."}'
        ),
        system_prompt="You are a strict technical interviewer. Only rephrase the question in simple terms. Never provide examples, hints, or solutions.",
    )
    cleaned = QuestionValidator.clean_for_speech(res.get("rephrased", ""))
    if not cleaned or "example" in cleaned.lower():
        cleaned = f"In simpler terms, could you explain {topic} in your own words?"

    response = f"To clarify: {cleaned}"
    session.last_agent_utterance = response
    return {
        "agent_response": response,
        "current_state": "LISTENING",
    }

async def correction_node(state: InterviewState) -> Dict[str, Any]:
    """UC33: Recognizes answer correction and re-evaluates active question with updated answer."""
    session = session_manager.get_or_create(state["session_id"])
    utterance = state.get("candidate_utterance", "")
    
    if session.candidate_answers:
        session.candidate_answers[-1]["answer_text"] += f" (Corrected: {utterance})"
        session.candidate_answers[-1]["is_corrected"] = True
    
    # Proceed to evaluate the corrected answer
    return await answer_processing_node(state, is_correction=True)

async def answer_processing_node(state: InterviewState, is_correction: bool = False) -> Dict[str, Any]:
    """UC13, UC14, UC16, UC18, UC19, UC21-27, UC31-35: Analyzes answer and determines routing."""
    session = session_manager.get_or_create(state["session_id"])
    utterance = state.get("candidate_utterance", "").strip()

    # G01: Prompt injection check
    is_safe, msg = guardrails.check_prompt_injection(utterance)
    if not is_safe:
        return {"agent_response": msg, "current_state": "LISTENING"}

    lowered = utterance.lower()

    # Hint and Example request check (Strict Assessment Policy: no hints or examples)
    hint_phrases = ("give me a hint", "can i get a hint", "hint please", "can you give a hint", "need a hint", "any hints")
    example_phrases = (
        "give me an example", "give an example", "can you give an example",
        "example please", "clarify with an example", "another example",
    )
    if _matches_any(lowered, hint_phrases) or _matches_any(lowered, example_phrases):
        response = "I can't provide hints or examples during the assessment, but I can clarify the question if needed, or you can choose to skip it."
        session.last_agent_utterance = response
        return {
            "agent_response": response,
            "current_state": "LISTENING",
        }

    # UC24: Repeat request check (Fast-Path)
    if any(w in lowered for w in ["repeat", "say that again", "pardon", "rephrase", "what was the question"]):
        return await repeat_node(state)

    # UC25: Pause request check (Fast-Path)
    if _matches_any(lowered, PAUSE_PHRASES):
        return await pause_node(state)

    # UC26: Resume request check (Fast-Path)
    if _matches_any(lowered, RESUME_PHRASES):
        return await resume_node(state)

    # G23: If session is paused, reject answer progression
    if session.is_paused:
        return {"agent_response": "The interview is paused. Please say 'resume' when you are ready to continue."}

    # UC31: Remaining questions query (Fast-Path)
    if any(w in lowered for w in ["how many questions", "how many more", "how many left", "questions remain", "questions left"]):
        return await remaining_questions_node(state)

    # UC32: Skip question request
    # If candidate explicitly requests to skip this question directly (e.g. "I would like to skip this question please")
    direct_skip_phrases = [
        "i would like to skip this question please",
        "skip this question please",
        "i want to skip this question please",
        "skip this question directly",
    ]
    if any(p in lowered for p in direct_skip_phrases):
        session.mark_permanent_skip(session.current_question_id or "")
        session.current_state = "LISTENING"
        if session.primary_question_count >= session.max_primary_questions:
            return await route_after_q3_node(state)
        q_state = await question_delivery_node(state)
        q_state["agent_response"] = f"Understood on skipping. {q_state.get('agent_response', '')}"
        q_state["skip_preference"] = "SKIP_ENTIRELY"
        return q_state

    # Dynamic Skip Confirmation & Revisit (e.g. "Can we skip this question?", "I don't know. Can we skip this?", "I want to come back to this later.")
    skip_phrases = [
        "skip", "skip question", "skip this question", "pass on this", 
        "next question please", "next question", "don't want to answer",
        "move to the next question", "move on to the next question", 
        "move to next question", "let's move to the next question",
        "i don't know can we skip", "can we skip", "come back to this later",
        "i want to come back to this later", "come back later"
    ]
    if any(w in lowered for w in skip_phrases):
        return await ask_skip_confirmation_node(state)

    # UC34: Question clarification / rephrase request (Fast-Path, no examples/hints)
    if any(w in lowered for w in ["can you clarify", "clarify please", "what do you mean", "rephrase the question", "clarify the question"]):
        return await example_clarification_node(state)

    # Skill confirmation check: if candidate repeats skill name when Q1 is fresh
    if session.primary_question_count == 1 and len(session.candidate_answers) == 0:
        supported_lowered = [s.lower() for s in settings.SUPPORTED_SKILLS]
        if lowered in supported_lowered or any(lowered == f"{s} please" for s in supported_lowered):
            active_q = session.current_question_text or "our first question"
            return {
                "agent_response": f"Great, let's proceed with {session.selected_skill or 'Python'}. Question one: {active_q}",
                "current_state": "LISTENING"
            }

    # UC33: Answer correction check
    if not is_correction and any(w in lowered for w in ["let me correct", "correction:", "sorry correction", "what i meant was", "actually wait"]):
        return await correction_node(state)

    # Off-topic Fast-Path check (prevents LLM fallback failures under rate-limits)
    off_topic_triggers = [
        "tell me a joke", "play some music", "sing a song", "write a poem",
        "what is the weather", "who is the president", "sing me a song",
        "tell a joke", "play music", "write poem"
    ]
    if any(ot in lowered for ot in off_topic_triggers):
        policy_decision = guardrails.handle_candidate_policy(
            session=session,
            candidate_intent="OFF_TOPIC",
            current_stage="PHASE_2",
            current_node="answer_processing",
            utterance=utterance,
        )
        session.last_agent_utterance = policy_decision.message
        if policy_decision.should_terminate:
            return await polite_termination_node(
                state,
                message=policy_decision.message,
                reason="REPEATED_OFF_TOPIC_INTERACTIONS"
            )
        return {"agent_response": policy_decision.message, "current_state": "LISTENING"}

    # Section 7: Voluntary Candidate Termination
    if _matches_any(lowered, VOLUNTARY_TERMINATION_PHRASES):
        return await voluntary_termination_node(state)

    # UC30: Explicit conclusion request (Fast-Path)
    conclusion_phrases = [
        "end interview", "conclude interview", 
        "conclude", "finish interview", "finish this interview", "finish this call",
        "finish call", "end the interview",
        "wrap up", "that's all", "thats all"
    ]
    if any(w in lowered for w in conclusion_phrases):
        return await conclusion_node(state)

    # UC09: Skill change request check
    skill_switch_triggers = [
        "change skill", "switch skill", "switch language", "change language",
        "change the programming language", "change programming language",
        "different skill", "different language", "switch to", "kavali", "questions in"
    ]
    if any(trigger in lowered for trigger in skill_switch_triggers):
        for s in sorted(settings.SUPPORTED_SKILLS, key=len, reverse=True):
            if s.lower() in lowered and s.lower() != (session.selected_skill or "").lower():
                return await skill_switch_node(state)
    if any(w in lowered for w in ["change skill", "switch skill", "switch language", "change language"]):
        return await skill_switch_node(state)

    # Phase B Optimization: Unified Single-Turn Structured LLM Call
    # Combines Intent Analysis, Concept Extraction, and Follow-Up Generation in ONE Gemini inference!
    unified_prompt = prompt_builder.build_unified_turn_prompt(
        skill=session.selected_skill or "Python",
        topic=session.current_question_topic or "Technical Fundamentals",
        subtopic="",
        current_question=session.current_question_text or "General Question",
        expected_concepts=session.current_expected_concepts,
        candidate_utterance=utterance,
        primary_question_count=session.primary_question_count,
        max_primary_questions=session.max_primary_questions,
        follow_up_count=session.follow_up_count_for_current_question,
        max_follow_ups=session.max_follow_ups_per_question,
        concepts_explored=session.concepts_mentioned,
    )

    decision = await model_service.invoke_json(unified_prompt, system_prompt=SYSTEM_INTERVIEWER_INSTRUCTION)
    intent = decision.get("detected_intent", "PROVIDE_ANSWER")
    concepts = decision.get("concepts_identified", [])
    missing = decision.get("missing_concepts", [])
    ack = decision.get("acknowledgment", "Got it.")
    needs_follow_up = decision.get("needs_follow_up", False)
    follow_up_q = decision.get("follow_up_question", "")

    # Clean text for speech
    ack = QuestionValidator.clean_for_speech(ack)
    follow_up_q = QuestionValidator.clean_for_speech(follow_up_q)

    # Save candidate response in session via MCP
    mcp_client.save_interview_response(
        session_id=session.session_id,
        question_id=session.current_question_id or "unknown",
        answer_text=utterance,
        concepts_identified=concepts,
        missing_concepts=missing,
    )

    # Route based on state and follow-up limits
    can_follow_up = session.can_ask_follow_up()

    # Revisit Mode: Answering a revisited question marks it completed and processes the next queued revisit or conclusion
    if session.question_visit_mode == "REVISIT":
        session.mark_revisit_completed(session.current_question_id or "", answered=True)
        if session.has_pending_revisit():
            return await route_after_q3_node(state)
        return await conclusion_node(state)

    # UC22: Universal Off-Topic Policy Enforcement across all stages
    if intent == "OFF_TOPIC":
        policy_decision = guardrails.handle_candidate_policy(
            session=session,
            candidate_intent="OFF_TOPIC",
            current_stage="PHASE_2",
            current_node="answer_processing",
            utterance=utterance,
        )
        session.last_agent_utterance = policy_decision.message
        if policy_decision.should_terminate:
            return await polite_termination_node(
                state,
                message=policy_decision.message,
                reason="REPEATED_OFF_TOPIC_INTERACTIONS"
            )
        return {"agent_response": policy_decision.message, "current_state": "LISTENING"}

    # UC21 & Handling Does Not Know
    if intent == "DOES_NOT_KNOW":
        if can_follow_up:
            follow_up_text = f"No worries at all, that is completely fine. How do you typically approach {session.current_question_topic or session.selected_skill} in your daily work?"
            session.record_follow_up(
                question_id=session.current_question_id or "",
                question_text=session.current_question_text or "",
                follow_up_text=follow_up_text,
                candidate_answer=utterance,
            )
            session.last_agent_utterance = follow_up_text
            return {
                "current_question_text": follow_up_text,
                "follow_up_count_for_current_question": session.follow_up_count_for_current_question,
                "current_state": "LISTENING",
                "agent_response": follow_up_text,
            }
        else:
            return await next_question_node(state)

    # UC16, UC18, UC19: Follow-up or Cross-Question
    if needs_follow_up and can_follow_up and follow_up_q and len(follow_up_q) > 10:
        # Validate generated question
        is_valid, _ = QuestionValidator.validate_question(
            follow_up_q,
            skill=session.selected_skill or "Python",
            presented_questions=session.presented_questions,
            max_words=settings.MAX_SPOKEN_RESPONSE_WORDS,
        )
        if not is_valid:
            follow_up_q = f"Could you elaborate on how you would implement that in practice?"

        spoken_utterance = f"{ack} {follow_up_q}".strip()
        session.record_follow_up(
            question_id=session.current_question_id or "",
            question_text=session.current_question_text or "",
            follow_up_text=follow_up_q,
            candidate_answer=utterance,
        )
        session.last_agent_utterance = spoken_utterance
        return {
            "current_question_text": follow_up_q,
            "follow_up_count_for_current_question": session.follow_up_count_for_current_question,
            "current_state": "LISTENING",
            "agent_response": spoken_utterance,
        }

    # Otherwise move to next question (UC15 / UC23)
    return await next_question_node(state)

async def elaboration_node(state: InterviewState, utterance: str, concepts: list, missing: list) -> Dict[str, Any]:
    """UC16: Short-answer elaboration."""
    session = session_manager.get_or_create(state["session_id"])
    
    # Generate elaboration prompt
    follow_up_res = await question_generator.generate_follow_up(
        session=session,
        candidate_answer=utterance,
        concepts_identified=concepts,
        missing_concepts=missing,
        follow_up_type="elaboration",
    )

    session.record_follow_up(
        question_id=session.current_question_id or "",
        question_text=session.current_question_text or "",
        follow_up_text=follow_up_res["question_text"],
        candidate_answer=utterance,
    )

    spoken = follow_up_res["full_spoken_utterance"]
    session.last_agent_utterance = spoken
    return {
        "current_question_text": follow_up_res["question_text"],
        "follow_up_count_for_current_question": session.follow_up_count_for_current_question,
        "current_state": "LISTENING",
        "agent_response": spoken,
    }

async def follow_up_node(state: InterviewState, utterance: str, concepts: list, missing: list) -> Dict[str, Any]:
    """UC18, UC19, UC23: Adaptive contextual follow-up or cross-question."""
    session = session_manager.get_or_create(state["session_id"])
    
    if not session.can_ask_follow_up():
        return await next_question_node(state)

    f_type = "cross_question" if len(missing) > 0 else "follow_up"
    follow_up_res = await question_generator.generate_follow_up(
        session=session,
        candidate_answer=utterance,
        concepts_identified=concepts,
        missing_concepts=missing,
        follow_up_type=f_type,
    )

    session.record_follow_up(
        question_id=session.current_question_id or "",
        question_text=session.current_question_text or "",
        follow_up_text=follow_up_res["question_text"],
        candidate_answer=utterance,
    )

    spoken = follow_up_res["full_spoken_utterance"]
    session.last_agent_utterance = spoken
    return {
        "current_question_text": follow_up_res["question_text"],
        "follow_up_count_for_current_question": session.follow_up_count_for_current_question,
        "current_state": "LISTENING",
        "agent_response": spoken,
    }

async def route_after_q3_node(state: InterviewState) -> Dict[str, Any]:
    """Routes after all primary questions are completed: delivers next FIFO revisit if queued, else conclusion."""
    session = session_manager.get_or_create(state["session_id"])
    session.active_question_stage = "STAGE_2_REVISIT" if session.has_pending_revisit() else "STAGE_2_COMPLETE"

    if session.has_pending_revisit():
        revisit_item = session.pop_revisit()
        session.current_question_id = revisit_item["id"]
        session.current_question_text = revisit_item["question_text"]
        session.current_question_topic = revisit_item.get("topic", "")
        session.current_expected_concepts = revisit_item.get("expected_concepts", [])
        session.question_visit_mode = "REVISIT"
        session.follow_up_count_for_current_question = 0
        session.current_state = "LISTENING"
        
        # Determine topic name or question phrasing naturally
        topic_phrase = f"the question about {revisit_item.get('topic', 'our previous topic')}"
        response = (
            f"Let's return to {topic_phrase}. "
            f"{revisit_item['question_text']}"
        )
        session.last_agent_utterance = response
        return {
            "current_question_id": revisit_item["id"],
            "current_question_text": revisit_item["question_text"],
            "current_question_topic": session.current_question_topic,
            "current_expected_concepts": session.current_expected_concepts,
            "question_visit_mode": "REVISIT",
            "active_question_stage": "STAGE_2_REVISIT",
            "current_state": "LISTENING",
            "agent_response": response,
        }
    return await conclusion_node(state)

async def next_question_node(state: InterviewState) -> Dict[str, Any]:
    """UC15: Transitions cleanly to the next primary question, next FIFO revisit, or conclusion."""
    session = session_manager.get_or_create(state["session_id"])
    
    # If in revisit mode, mark current question completed and process NEXT question in FIFO queue
    if session.question_visit_mode == "REVISIT":
        session.mark_revisit_completed(session.current_question_id or "", answered=True)
        if session.has_pending_revisit():
            return await route_after_q3_node(state)
        return await conclusion_node(state)

    if session.primary_question_count >= session.max_primary_questions:
        session.q3_completed = True
        return await route_after_q3_node(state)

    # Deliver next primary question
    ack = "Thank you for that response. Let's move on to the next topic."
    q_state = await question_delivery_node(state)
    q_state["agent_response"] = f"{ack} {q_state.get('agent_response', '')}"
    return q_state

async def repeat_node(state: InterviewState) -> Dict[str, Any]:
    """UC24: Repeats the active question without incrementing question counts."""
    session = session_manager.get_or_create(state["session_id"])
    active_q = session.current_question_text or "Could you explain your technical experience in your chosen skill?"
    response = f"Certainly, let me repeat the question: {active_q}"
    session.last_agent_utterance = response
    return {
        "agent_response": response,
        "current_state": "LISTENING",
    }

async def pause_node(state: InterviewState) -> Dict[str, Any]:
    """UC25, G09, G23: Pauses the interview."""
    session = session_manager.get_or_create(state["session_id"])
    session.is_paused = True
    session.previous_state = session.current_state
    session.current_state = "PAUSED"
    response = "The interview is now paused. Take your time, and just say 'resume' or 'I am back' when you are ready to continue."
    session.last_agent_utterance = response
    return {
        "is_paused": True,
        "current_state": "PAUSED",
        "agent_response": response,
    }

async def resume_node(state: InterviewState) -> Dict[str, Any]:
    """UC26, G10: Resumes the paused interview."""
    session = session_manager.get_or_create(state["session_id"])
    session.is_paused = False
    session.current_state = session.previous_state or "LISTENING"
    active_q = session.current_question_text or ""
    response = f"Welcome back. Resuming our interview. Our current question was: {active_q}"
    session.last_agent_utterance = response
    return {
        "is_paused": False,
        "current_state": session.current_state,
        "agent_response": response,
    }

async def skill_switch_node(state: InterviewState) -> Dict[str, Any]:
    """UC09, G11: Skill is locked once the interview begins; reject switches and remain in current state."""
    session = session_manager.get_or_create(state["session_id"])
    locked_skill = session.selected_skill or "Python"
    active_q = session.current_question_text or "our current question"
    response = (
        f"Your interview skill is locked to {locked_skill} for this session and cannot be changed. "
        f"Let's continue with our question: {active_q}"
    )
    session.last_agent_utterance = response
    return {
        "agent_response": response,
        "current_state": "LISTENING",
    }

async def recovery_node(state: InterviewState) -> Dict[str, Any]:
    """UC28, UC29, G16-G20: Silence or provider recovery."""
    session = session_manager.get_or_create(state["session_id"])
    response = "I did not quite catch that. Could you please repeat or elaborate on your answer?"
    session.last_agent_utterance = response
    return {
        "agent_response": response,
        "current_state": "LISTENING",
    }

async def voluntary_termination_node(state: InterviewState) -> Dict[str, Any]:
    """Section 7: Handles voluntary candidate termination at any stage."""
    session = session_manager.get_or_create(state["session_id"])
    response = "Understood. We'll end the interview here. Thank you for your time."
    session.terminal_outcome = "TERMINATED_BY_CANDIDATE"
    session.terminate_session("TERMINATED_BY_CANDIDATE")
    session.finalize_assessment()
    session.mark_cleanup_completed()
    session.last_agent_utterance = response
    return {
        "is_completed": True,
        "session_status": "TERMINATED",
        "stage_1_status": "TERMINATED",
        "current_state": "TERMINATED",
        "terminal_outcome": "TERMINATED_BY_CANDIDATE",
        "termination_reason": "TERMINATED_BY_CANDIDATE",
        "cleanup_completed": True,
        "agent_response": response,
    }

async def conclusion_node(state: InterviewState) -> Dict[str, Any]:
    """Stage 3: Interview Conclusion, Assessment Finalization, and Inquiries."""
    session = session_manager.get_or_create(state["session_id"])
    session.is_completed = True

    if session.termination_reason:
        response = session.last_agent_utterance or MSG_POLITE_TERMINATE
        return {
            "is_completed": True,
            "session_status": "TERMINATED",
            "stage_1_status": "TERMINATED",
            "current_state": "TERMINATED",
            "terminal_outcome": session.terminal_outcome or "TERMINATED",
            "termination_reason": session.termination_reason,
            "agent_response": response,
        }

    utterance = (state.get("candidate_utterance") or "").strip()
    lowered = utterance.lower()

    # If candidate speaks during conclusion, handle specific conclusion inquiries
    if utterance and session.current_state == "CONCLUSION":
        # 1. Section 7: Voluntary Termination
        if any(w in lowered for w in ["stop the interview", "end this session", "don't want to continue", "dont want to continue", "terminate the interview", "terminate interview", "stop interview", "quit interview", "i want to stop"]):
            return await voluntary_termination_node(state)

        # 2. Section 6.1: Candidate asks whether they passed
        if any(w in lowered for w in ["did i pass", "did i clear", "pass or fail", "pass the interview", "clear the interview", "am i selected", "will i be selected", "did i get selected"]):
            response = "Your responses have been recorded. The assessment outcome will be determined through the evaluation process."
            session.last_agent_utterance = response
            return {
                "current_state": "CONCLUSION",
                "is_completed": True,
                "agent_response": response,
            }

        # 3. Section 6.2: Candidate asks for feedback
        if any(w in lowered for w in ["feedback", "how did i perform", "how was my performance", "how did i do", "how i did", "any feedback", "my score"]):
            response = "Your responses have been recorded for assessment. Detailed feedback will be available through the assessment results process."
            session.last_agent_utterance = response
            return {
                "current_state": "CONCLUSION",
                "is_completed": True,
                "agent_response": response,
            }

        # 4. Section 6.3: Candidate asks whether the interview is over
        if any(w in lowered for w in ["is the interview over", "is it over", "are we done", "is this over", "we are done", "interview over"]):
            response = "Yes, we've completed your interview. Thank you for your time."
            session.last_agent_utterance = response
            return {
                "current_state": "CONCLUSION",
                "is_completed": True,
                "agent_response": response,
            }

        # 5. Section 6.4: Candidate attempts to answer another question
        if any(w in lowered for w in ["another question", "one more question", "answer another", "answer one more", "try another"]):
            response = "We've already completed the interview and concluded all questions. Your responses have been recorded for assessment."
            session.last_agent_utterance = response
            return {
                "current_state": "CONCLUSION",
                "is_completed": True,
                "agent_response": response,
            }

        # 6. Section 5 & 6.5: Candidate says thank you
        if any(w in lowered for w in ["thank you", "thanks", "thank u", "thx"]):
            return _finalize_completed_session(
                session,
                "You're welcome. Your interview has now been completed. Have a good day.",
            )

        # 7. Section 6.5: Candidate says goodbye
        if any(w in lowered for w in ["goodbye", "bye", "see you", "have a good day", "have a great day"]):
            return _finalize_completed_session(
                session,
                "Thank you. Your interview has now been completed. Have a great day!",
            )

        # 8. General acknowledgement / other closing remarks
        return _finalize_completed_session(
            session,
            "Your interview has now been completed. Thank you for your time and have a good day.",
        )

    # Initial conclusion entry (from Stage 2 after Q3/revisits are all completed)
    session.current_state = "CONCLUSION"
    session.active_question_stage = "STAGE_3_CONCLUSION"
    session.conclusion_started = True
    session.finalize_assessment()

    response = (
        "That was the last question. We've completed all the questions in your interview, "
        "and that concludes our questions today. Thank you for participating."
    )
    session.last_agent_utterance = response
    return {
        "current_state": "CONCLUSION",
        "is_completed": True,
        "active_question_stage": "STAGE_3_CONCLUSION",
        "conclusion_started": True,
        "assessment_finalized": True,
        "agent_response": response,
    }
