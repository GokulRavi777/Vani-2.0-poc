"""
LiveKit Service: Token Generation and Room Dispatch Management.
"""

import logging
from typing import Dict, Any, Optional
from livekit.api import AccessToken, VideoGrants, LiveKitAPI, CreateAgentDispatchRequest
from config.settings import settings

logger = logging.getLogger("vani.backend.livekit")


class LiveKitService:
    def __init__(self) -> None:
        self.api_key = settings.LIVEKIT_API_KEY
        self.api_secret = settings.LIVEKIT_API_SECRET
        self.livekit_url = settings.LIVEKIT_URL

    def generate_candidate_token(
        self,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        metadata: Dict[str, Any] = None,
    ) -> str:
        """Generates a secure LiveKit connection JWT for the candidate."""
        grants = VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )

        meta_str = ""
        if metadata:
            import json
            meta_str = json.dumps(metadata)

        token = (
            AccessToken(self.api_key, self.api_secret)
            .with_identity(participant_identity)
            .with_name(participant_name)
            .with_grants(grants)
            .with_metadata(meta_str)
        )
        return token.to_jwt()

    async def dispatch_agent(
        self,
        room_name: str,
        agent_name: str = "vani-interviewer",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Dispatches the VANI agent to the specified room with optional skill metadata."""
        try:
            import json
            lk = LiveKitAPI(self.livekit_url, self.api_key, self.api_secret)
            meta_str = json.dumps(metadata) if metadata else ""
            req = CreateAgentDispatchRequest(
                agent_name=agent_name,
                room=room_name,
                metadata=meta_str,
            )
            dispatch = await lk.agent_dispatch.create_dispatch(req)
            logger.info("Successfully dispatched agent '%s' to room '%s' (dispatch_id: %s)", agent_name, room_name, dispatch.id)
            await lk.aclose()
            return dispatch.id
        except Exception as e:
            logger.warning("Agent dispatch to room '%s' notice: %s", room_name, e)
            return None


livekit_service = LiveKitService()
