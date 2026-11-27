import re
import json
import logging
from typing import Any, Dict, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import settings

from vani.schemas.models import SkipIntentDecision, SkipPreferenceDecision
from vani.llm.prompts import (
    SKIP_INTENT_RECOGNITION_PROMPT,
    SKIP_PREFERENCE_CLASSIFICATION_PROMPT,
    PHASE1_INTENT_CLASSIFICATION_PROMPT,
)

logger = logging.getLogger("vani.llm")

class GeminiModelService:
    def __init__(self) -> None:
        self.api_key = settings.GEMINI_API_KEY
        self.model_name = settings.GEMINI_MODEL
        self._llm: Optional[ChatGoogleGenerativeAI] = None

    def get_llm(self) -> ChatGoogleGenerativeAI:
        if self._llm is None:
            self._llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=self.api_key,
                temperature=0.3,
                timeout=15.0,
                max_retries=2,
            )
        return self._llm

    @staticmethod
    def _build_messages(prompt: str, system_prompt: Optional[str] = None) -> list:
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        return messages

    async def invoke_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Invokes Gemini asynchronously and reliably parses JSON output."""
        llm = self.get_llm()
        messages = self._build_messages(prompt, system_prompt)
        try:
            response = await llm.ainvoke(messages)
            text = self._extract_text(response.content)
            return self._parse_json_from_text(text)
        except Exception as e:
            logger.error(f"Error invoking Gemini model: {e}")
            return {"error": str(e), "raw_text": ""}

    def invoke_json_sync(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Invokes Gemini synchronously and reliably parses JSON output."""
        llm = self.get_llm()
        messages = self._build_messages(prompt, system_prompt)
        try:
            response = llm.invoke(messages)
            text = self._extract_text(response.content)
            return self._parse_json_from_text(text)
        except Exception as e:
            logger.error(f"Error invoking Gemini model (sync): {e}")
            return {"error": str(e), "raw_text": ""}

    def _extract_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Sometimes Gemini returns a list of dicts [{'type': 'text', 'text': '...'}]
            chunks = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    chunks.append(item["text"])
                elif isinstance(item, str):
                    chunks.append(item)
            return " ".join(chunks)
        return str(content)

    def _parse_json_from_text(self, text: str) -> Dict[str, Any]:
        """Extracts JSON substring or parses raw text."""
        # Remove markdown code fences if present
        clean = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean)
        if match:
            clean = match.group(1).strip()
        
        try:
            return json.loads(clean)
        except Exception:
            # Try to locate { ... } block
            start = clean.find("{")
            end = clean.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(clean[start:end+1])
                except Exception:
                    pass
        return {"raw_text": text}

    async def classify_phase1_intent(
        self,
        candidate_utterance: str,
        current_node: str = "greeting",
        last_agent_utterance: str = "",
        readiness_status: str = "PENDING",
        clarification_count: int = 0,
    ) -> Dict[str, Any]:
        """Classifies candidate intent in Phase 1 with deterministic fast-paths and LLM fallback."""
        clean = (candidate_utterance or "").strip()
        if not clean:
            return {"intent": "NO_INPUT", "confidence": 1.0, "reasoning_summary": "Empty transcript"}

        lowered = clean.lower()

        # Fast-Path 1: Off-Topic / Unrelated Commands
        off_topic_phrases = [
            "tell me a joke", "tell a joke", "what is the weather", "what's the weather",
            "weather today", "sing a song", "write a poem", "play music", "play a song",
            "who won the match", "who is the president", "tell me a story", "what is 2+2"
        ]
        if any(p in lowered for p in off_topic_phrases):
            return {"intent": "OFF_TOPIC", "confidence": 1.0, "reasoning_summary": "Unrelated off-topic prompt"}

        # Fast-Path 2: Nervousness
        nervous_phrases = ["nervous", "a bit nervous", "little nervous", "anxious", "scared", "jittery", "feeling tense", "stressed"]
        if any(p in lowered for p in nervous_phrases):
            return {"intent": "NERVOUSNESS", "confidence": 1.0, "reasoning_summary": "Candidate expressed nervousness"}

        # Fast-Path 3: Request Time / Preparation Wait
        time_phrases = [
            "give me a minute", "give me a moment", "one minute", "need a minute",
            "need a moment", "wait a second", "wait a minute", "hold on", "give me time",
            "couple of minutes", "few seconds", "few moments", "wait for me"
        ]
        if any(p in lowered for p in time_phrases):
            return {"intent": "REQUEST_TIME", "confidence": 1.0, "reasoning_summary": "Candidate requested preparation time"}

        # Fast-Path 4: Questions about Vani
        vani_phrases = ["what is vani", "who is vani", "who are you", "what are you", "tell me about vani", "tell me about yourself", "are you an ai"]
        if any(p in lowered for p in vani_phrases):
            return {"intent": "VANI_QUESTION", "confidence": 1.0, "reasoning_summary": "Candidate asked about Vani"}

        # Fast-Path 5: Questions about Process
        process_phrases = [
            "how does this interview work", "how does the interview work", "how does it work",
            "what is the process", "what is the format", "how many questions", "rules of the interview",
            "what happens in the interview", "what should i expect"
        ]
        if any(p in lowered for p in process_phrases):
            return {"intent": "PROCESS_QUESTION", "confidence": 1.0, "reasoning_summary": "Candidate asked about the interview process"}

        # Fast-Path 6: Not Ready / Cancellation
        not_ready_phrases = [
            "i don't want to continue", "i dont want to continue", "i don't want to proceed",
            "i dont want to proceed", "i want to stop", "cancel interview", "exit", "quit",
            "no i am not ready", "not ready", "no not ready", "no not yet", "i need more time"
        ]
        if any(p in lowered for p in not_ready_phrases):
            intent_val = "NOT_READY_CONFIRMATION" if current_node == "readiness_confirmation" else "NOT_READY"
            return {"intent": intent_val, "confidence": 1.0, "reasoning_summary": "Candidate declined readiness"}

        # Fast-Path 7: Ready Confirmation / Ready
        ready_phrases = [
            "i am ready", "i'm ready", "let's start", "lets start", "ready to begin", "ready to start",
            "ready now", "yes i am ready", "yes let's start", "yes lets start", "ready", "begin", "start"
        ]
        if any(p in lowered for p in ready_phrases) or (lowered in ["yes", "yeah", "yep", "sure", "ok", "okay"]):
            intent_val = "READY_CONFIRMATION" if current_node == "readiness_confirmation" else "READY"
            return {"intent": intent_val, "confidence": 1.0, "reasoning_summary": "Candidate confirmed readiness"}

        # Fast-Path 8: Social Response
        social_phrases = [
            "doing good", "doing well", "i am good", "i'm good", "i am fine", "i'm fine",
            "doing great", "all good", "pretty good", "doing okay", "fine thanks", "good thanks"
        ]
        if any(p in lowered for p in social_phrases):
            return {"intent": "SOCIAL_RESPONSE", "confidence": 1.0, "reasoning_summary": "Candidate responded to greeting"}

        # Fast-Path 9: Clarification
        clarify_phrases = ["what did you say", "repeat that", "say again", "pardon", "could you repeat"]
        if any(p in lowered for p in clarify_phrases):
            return {"intent": "CLARIFICATION", "confidence": 1.0, "reasoning_summary": "Candidate asked for clarification"}

        # LLM Fallback: Invoke Gemini with context
        prompt = PHASE1_INTENT_CLASSIFICATION_PROMPT.format(
            current_node=current_node,
            last_agent_utterance=last_agent_utterance or "None",
            readiness_status=readiness_status,
            clarification_count=clarification_count,
            candidate_utterance=clean,
        )
        try:
            res = await self.invoke_json(prompt)
            intent = res.get("intent", "UNCLEAR")
            valid_intents = [
                "SOCIAL_RESPONSE", "NERVOUSNESS", "VANI_QUESTION", "PROCESS_QUESTION",
                "READY", "REQUEST_TIME", "NOT_READY", "READY_CONFIRMATION",
                "NOT_READY_CONFIRMATION", "CLARIFICATION", "OFF_TOPIC", "UNCLEAR", "NO_INPUT"
            ]
            if intent not in valid_intents:
                intent = "UNCLEAR"
            return {
                "intent": intent,
                "confidence": float(res.get("confidence", 0.8)),
                "reasoning_summary": str(res.get("reasoning_summary", "")),
                "requires_clarification": bool(res.get("requires_clarification", False)),
            }
        except Exception as e:
            logger.error(f"Error in classify_phase1_intent: {e}")
            return {"intent": "UNCLEAR", "confidence": 0.5, "reasoning_summary": str(e)}

    async def classify_skip_intent(self, candidate_utterance: str, current_question: str) -> SkipIntentDecision:
        """Classifies if candidate wants to skip the current question using structured output."""
        prompt = SKIP_INTENT_RECOGNITION_PROMPT.format(
            candidate_utterance=candidate_utterance,
            current_question=current_question,
        )
        data = await self.invoke_json(prompt)
        intent = data.get("intent", "OTHER")
        if intent not in ["SKIP_REQUEST", "OTHER"]:
            intent = "OTHER"
        return SkipIntentDecision(
            intent=intent,
            confidence=float(data.get("confidence", 1.0)),
            reasoning=str(data.get("reasoning", "")),
        )

    async def classify_skip_preference(self, candidate_utterance: str, current_question: str) -> SkipPreferenceDecision:
        """Classifies candidate preference between permanent skip vs revisit after next question."""
        prompt = SKIP_PREFERENCE_CLASSIFICATION_PROMPT.format(
            candidate_utterance=candidate_utterance,
        )
        data = await self.invoke_json(prompt)
        pref = data.get("preference", "UNCLEAR")
        if pref not in ["SKIP_ENTIRELY", "REVISIT_AFTER_NEXT", "UNCLEAR"]:
            pref = "UNCLEAR"
        return SkipPreferenceDecision(
            preference=pref,
            confidence=float(data.get("confidence", 1.0)),
            reasoning=str(data.get("reasoning", "")),
        )

model_service = GeminiModelService()
