from pydantic import BaseModel, Field

from nova_core.agent_runtime.models import AgentChatResult


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=100)


class AgentChatData(AgentChatResult):
    pass


class AgentChatDataWrapper(BaseModel):
    data: AgentChatData


__all__ = ["AgentChatData", "AgentChatDataWrapper", "AgentChatRequest"]
