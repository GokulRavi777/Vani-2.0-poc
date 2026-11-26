import logging
import asyncio
from typing import Any
from dotenv import load_dotenv

# Preload environment variables before anything else
from config.settings import settings

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    cli,
)
from livekit.plugins import gnani, silero
from vani.llm.livekit_adapter import VaniInterviewerLLM
from vani.session.manager import session_manager

logger = logging.getLogger("vani.agent")

class VaniInterviewAgent(Agent):
    """VANI 2.0 Conversational AI Technical Interviewer Agent."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(
            instructions=(
                "You are VANI, a professional conversational AI technical interviewer. "
                "You conduct technical interviews with clear, concise spoken dialogue. "
                "Never use markdown formatting, bullet points, asterisks, or code blocks in speech."
            )
        )

    async def on_enter(self) -> None:
        """UC01: When agent enters the room, automatically trigger the welcome greeting."""
        logger.info(f"VaniInterviewAgent entered room for session {self.session_id}")
        self.session.generate_reply()


# Initialize LiveKit Agent Server with 0 idle processes to fit within Render Free Tier (512 MB RAM)
server = AgentServer(
    num_idle_processes=0,
    initialize_process_timeout=60.0,
)

@server.rtc_session(agent_name=settings.AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    session_id = ctx.room.name
    logger.info(f"Initializing VANI 2.0 Interview Session for room: {session_id}")

    # Section 8 Requirement: Initialize session state with preselected Python skill
    sess = session_manager.get_or_create(session_id)
    sess.selected_skill = "Python"
    if len(sess.candidate_answers) == 0:
        sess.greeting_completed = False
        sess.current_state = "GREETING"
        sess.stage_1_status = "NOT_STARTED"

    ctx.log_context_fields = {
        "room": session_id,
        "agent": settings.AGENT_NAME,
    }

    try:
        # Initialize Voice Pipeline
        # 1. Silero VAD for turn and voice activity detection
        vad_plugin = silero.VAD.load(
            min_speech_duration=0.05,
            min_silence_duration=0.55,
            prefix_padding_duration=0.5,
        )

        # 2. Gnani STT for candidate speech recognition
        stt_plugin = gnani.STT(
            language=settings.GNANI_STT_LANGUAGE,
            api_key=settings.GNANI_API_KEY,
            use_streaming=settings.GNANI_STT_USE_STREAMING,
        )

        # 3. Gnani TTS for interviewer speech generation
        tts_plugin = gnani.TTS(
            voice=settings.GNANI_TTS_VOICE,
            model=settings.GNANI_TTS_MODEL,
            language=settings.GNANI_TTS_LANGUAGE,
            api_key=settings.GNANI_API_KEY,
        )

        # 4. LangGraph + LangChain + Gemini LLM Orchestrator
        llm_adapter = VaniInterviewerLLM(session_id=session_id)

        # Configure session
        session = AgentSession(
            stt=stt_plugin,
            vad=vad_plugin,
            llm=llm_adapter,
            tts=tts_plugin,
            turn_handling=TurnHandlingOptions(
                interruption={
                    "resume_false_interruption": True,
                    "false_interruption_timeout": 1.0,
                },
                preemptive_generation={"enabled": False}, # Keep disabled for strict graph validation
            ),
        )
        llm_adapter.set_agent_session(session, ctx.room)

        agent = VaniInterviewAgent(session_id=session_id)

        @session.on("close")
        def on_session_close(*args: Any) -> None:
            logger.info(f"Cleaning up in-memory session memory on session close for: {session_id}")
            llm_adapter.cancel_prep_timer()
            llm_adapter.cancel_answer_timer()
            try:
                from backend.app.database import SessionLocal
                from backend.app.models import InterviewSession
                from datetime import datetime
                sess_obj = session_manager.get(session_id)
                with SessionLocal() as db:
                    db_sess = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
                    if db_sess and db_sess.session_status in ["CREATED", "CONNECTING", "IN_PROGRESS"]:
                        if sess_obj and sess_obj.is_terminated():
                            db_sess.session_status = sess_obj.session_status
                            db_sess.terminal_outcome = sess_obj.terminal_outcome
                        else:
                            db_sess.session_status = "TERMINATED"
                            db_sess.terminal_outcome = "CANDIDATE_DISCONNECTED"
                        if not db_sess.completed_at:
                            db_sess.completed_at = datetime.utcnow()
                            if db_sess.started_at:
                                db_sess.duration_seconds = round((db_sess.completed_at - db_sess.started_at).total_seconds(), 2)
                        db.commit()
            except Exception as db_err:
                logger.warning(f"Failed to record session disconnect in DB: {db_err}")
            session_manager.cleanup(session_id)

        async def on_shutdown() -> None:
            logger.info(f"Cleaning up in-memory session memory on job shutdown for: {session_id}")
            llm_adapter.cancel_prep_timer()
            llm_adapter.cancel_answer_timer()
            session_manager.cleanup(session_id)

        ctx.add_shutdown_callback(on_shutdown)

        # 1. Connect agent to the LiveKit room
        await ctx.connect()
        logger.info(f"VANI connected to room: {session_id}. Waiting for candidate participant to join...")

        # 2. Wait until the candidate actively connects to the room
        participant = await ctx.wait_for_participant()
        logger.info(f"Candidate participant '{participant.identity}' joined room {session_id}.")

        # 3. Synchronize session status in SQLite database to IN_PROGRESS
        try:
            from backend.app.database import SessionLocal
            from backend.app.models import InterviewSession
            with SessionLocal() as db:
                db_sess = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
                if db_sess and db_sess.session_status in ["CREATED", "CONNECTING"]:
                    db_sess.session_status = "IN_PROGRESS"
                    db.commit()
        except Exception as db_err:
            logger.warning(f"Failed to update session status to IN_PROGRESS in DB: {db_err}")

        # 4. Brief 1.0s buffer allowing candidate WebRTC audio tracks & playback to establish cleanly
        await asyncio.sleep(1.0)

        # 5. Start agent session (invokes agent.on_enter which triggers greeting)
        await session.start(agent=agent, room=ctx.room)

        # 6. Reconnection listener for candidate page reloads before answering questions
        @ctx.room.on("participant_connected")
        def on_participant_connected(remote_p: Any) -> None:
            p_identity = getattr(remote_p, "identity", str(remote_p))
            logger.info(f"Candidate participant reconnected: {p_identity} in room {session_id}")
            current_sess = session_manager.get(session_id)
            if current_sess and len(current_sess.candidate_answers) == 0:
                async def _delayed_greet():
                    await asyncio.sleep(1.0)
                    logger.info(f"Repeating greeting for candidate {p_identity} upon reconnection")
                    current_sess.greeting_completed = False
                    current_sess.current_state = "GREETING"
                    session.generate_reply()
                asyncio.create_task(_delayed_greet())
    except Exception as e:
        logger.exception(f"Fatal error in VANI entrypoint for room {session_id}: {e}")
        raise


if __name__ == "__main__":
    cli.run_app(server)
