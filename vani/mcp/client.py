from typing import Dict, Any, List, Optional
from langchain_core.tools import tool
from vani.mcp.server import (
    list_available_skills as _list_skills,
    get_skill_details as _get_details,
    get_skill_few_shot_prompt as _get_skill_prompt,
    select_interview_skill as _select_skill,
    get_next_question as _get_question,
    aget_next_question as _aget_question,
    save_interview_response as _save_response,
)

@tool
def list_available_skills_tool() -> Dict[str, Any]:
    """List all supported technical interview skills with descriptions."""
    return _list_skills()

@tool
def get_skill_details_tool(skill: str) -> Dict[str, Any]:
    """Retrieve syllabus topics and metadata for a specific technical skill."""
    return _get_details(skill)

@tool
def get_skill_few_shot_prompt_tool(skill: str, sub_skill: Optional[str] = None) -> Dict[str, Any]:
    """Fetch the system prompt and few-shot question generation prompt for a mother skill or sub-skill from DB."""
    return _get_skill_prompt(skill, sub_skill=sub_skill)

@tool
def select_interview_skill_tool(session_id: str, skill: str) -> Dict[str, Any]:
    """Select the active technical skill for the interview session."""
    return _select_skill(session_id, skill)

@tool
def get_next_question_tool(session_id: str, skill: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve the next suitable primary technical question for the candidate."""
    return _get_question(session_id, skill)

@tool
def save_interview_response_tool(
    session_id: str,
    question_id: str,
    answer_text: str,
    concepts_identified: Optional[List[str]] = None,
    missing_concepts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record candidate answer and detected technical concepts in session memory."""
    return _save_response(session_id, question_id, answer_text, concepts_identified, missing_concepts)

VANI_MCP_TOOLS = [
    list_available_skills_tool,
    get_skill_details_tool,
    get_skill_few_shot_prompt_tool,
    select_interview_skill_tool,
    get_next_question_tool,
    save_interview_response_tool,
]

# Direct programmatic access
class MCPClient:
    @staticmethod
    def list_available_skills() -> Dict[str, Any]:
        return _list_skills()

    @staticmethod
    def get_skill_details(skill: str) -> Dict[str, Any]:
        return _get_details(skill)

    @staticmethod
    def get_skill_few_shot_prompt(skill: str, sub_skill: Optional[str] = None) -> Dict[str, Any]:
        return _get_skill_prompt(skill, sub_skill=sub_skill)

    @staticmethod
    def select_interview_skill(session_id: str, skill: str) -> Dict[str, Any]:
        return _select_skill(session_id, skill)

    @staticmethod
    def get_next_question(session_id: str, skill: Optional[str] = None, sub_skill: Optional[str] = None) -> Dict[str, Any]:
        return _get_question(session_id, skill, sub_skill=sub_skill)

    @staticmethod
    async def aget_next_question(session_id: str, skill: Optional[str] = None, sub_skill: Optional[str] = None) -> Dict[str, Any]:
        return await _aget_question(session_id, skill, sub_skill=sub_skill)

    @staticmethod
    def save_interview_response(
        session_id: str,
        question_id: str,
        answer_text: str,
        concepts_identified: Optional[List[str]] = None,
        missing_concepts: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return _save_response(session_id, question_id, answer_text, concepts_identified, missing_concepts)

mcp_client = MCPClient()
