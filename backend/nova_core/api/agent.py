from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from nova_core.agent_runtime.runtime import AgentRuntime
from nova_core.api.security import require_api_token
from nova_core.logging_config import correlation_id_var
from nova_core.schemas.agent import AgentChatDataWrapper, AgentChatRequest

router = APIRouter(prefix="/api/chat", tags=["Agent"], dependencies=[Depends(require_api_token)])


def get_agent_runtime(request: Request) -> AgentRuntime:
    runtime = getattr(request.app.state, "agent_runtime", None)
    if not isinstance(runtime, AgentRuntime):
        raise RuntimeError("The agent runtime is unavailable.")
    return runtime


@router.post("", response_model=AgentChatDataWrapper)
async def chat(
    request: AgentChatRequest,
    raw_request: Request,
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
) -> AgentChatDataWrapper:
    correlation_id = (
        correlation_id_var.get() or raw_request.headers.get("X-Correlation-ID") or str(uuid4())
    )
    result = await runtime.chat(
        request.message,
        correlation_id=correlation_id,
        client_request_id=request.client_request_id,
    )
    return AgentChatDataWrapper(data=result.model_dump(mode="json"))
