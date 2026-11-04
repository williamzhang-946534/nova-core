from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.memory.models import MemorySourceType, MemoryType
from arvuno_core.memory.service import MemoryService
from arvuno_core.schemas.memory import (
    HistoryReferenceListData,
    MemoryCleanupWrapper,
    MemoryCorrectRequest,
    MemoryCreateRequest,
    MemoryData,
    MemoryDeleteWrapper,
    MemoryListData,
    MemoryProcedureData,
    MemoryProcedureValidationRequest,
    MemoryProcedureVersionRequest,
    MemoryRetrievalData,
    MemoryRetrievalRequest,
    MemoryRevisionListData,
    MemoryUpdateRequest,
    PreferenceCreateRequest,
    PreferenceData,
    PreferenceListData,
    PreferenceUpdateRequest,
)

router = APIRouter(
    prefix="/api/memories",
    tags=["Memory"],
    dependencies=[Depends(require_api_token)],
)
retrieval_router = APIRouter(
    prefix="/api/memory-retrieval",
    tags=["Memory"],
    dependencies=[Depends(require_api_token)],
)
preference_router = APIRouter(
    prefix="/api/memory-preferences",
    tags=["Memory"],
    dependencies=[Depends(require_api_token)],
)


def get_memory_service(request: Request) -> MemoryService:
    service = getattr(request.app.state, "memory_service", None)
    if not isinstance(service, MemoryService):
        raise RuntimeError("The memory service is unavailable.")
    return service


@router.post("", response_model=MemoryData, status_code=201)
async def create_memory(
    request: MemoryCreateRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryData:
    return MemoryData(data=await service.create_memory(request))


@router.get("", response_model=MemoryListData)
async def list_memories(
    service: Annotated[MemoryService, Depends(get_memory_service)],
    memory_type: MemoryType | None = None,
    status: Literal[
        "active", "candidate", "corrected", "superseded", "expired", "archived", "current"
    ] = "current",
    source_type: MemorySourceType | None = None,
    keyword: str | None = Query(default=None, max_length=200),
    environment_id: str | None = Query(default=None, max_length=36),
    space_id: str | None = Query(default=None, max_length=36),
    entity_id: str | None = Query(default=None, max_length=36),
    include_expired: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> MemoryListData:
    items, total = await service.list_memories(
        memory_type=memory_type,
        status=status,
        source_type=source_type,
        keyword=keyword,
        environment_id=environment_id,
        space_id=space_id,
        entity_id=entity_id,
        include_expired=include_expired,
        page=page,
        page_size=page_size,
    )
    return MemoryListData(data=items, page=page, page_size=page_size, total=total)


@router.post("/cleanup", response_model=MemoryCleanupWrapper)
async def cleanup_memories(
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryCleanupWrapper:
    return MemoryCleanupWrapper(data=await service.cleanup())


@router.get("/{memory_id}", response_model=MemoryData)
async def get_memory(
    memory_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryData:
    return MemoryData(data=await service.get_memory(memory_id))


@router.patch("/{memory_id}", response_model=MemoryData)
async def update_memory(
    memory_id: str,
    request: MemoryUpdateRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryData:
    return MemoryData(data=await service.update_memory(memory_id, request))


@router.post("/{memory_id}/correct", response_model=MemoryData)
async def correct_memory(
    memory_id: str,
    request: MemoryCorrectRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryData:
    return MemoryData(data=await service.correct_memory(memory_id, request))


@router.post("/{memory_id}/confirm", response_model=MemoryData)
async def confirm_memory(
    memory_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryData:
    return MemoryData(data=await service.confirm_memory(memory_id))


@router.delete("/{memory_id}", response_model=MemoryDeleteWrapper)
async def delete_memory(
    memory_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryDeleteWrapper:
    result = await service.delete_memory(memory_id)
    return MemoryDeleteWrapper(data={"id": result["id"], "deleted": True})


@router.get("/{memory_id}/revisions", response_model=MemoryRevisionListData)
async def get_memory_revisions(
    memory_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryRevisionListData:
    return MemoryRevisionListData(data=await service.revisions(memory_id))


@router.get("/{memory_id}/history", response_model=HistoryReferenceListData)
async def get_related_history(
    memory_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> HistoryReferenceListData:
    return HistoryReferenceListData(data=await service.related_history(memory_id))


@router.post(
    "/{memory_id}/procedure-versions",
    response_model=MemoryProcedureData,
    status_code=201,
)
async def create_procedure_version(
    memory_id: str,
    request: MemoryProcedureVersionRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryProcedureData:
    return MemoryProcedureData(data=await service.create_procedure_version(memory_id, request))


@router.post("/{memory_id}/procedure-validations", response_model=MemoryProcedureData)
async def validate_procedure(
    memory_id: str,
    request: MemoryProcedureValidationRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryProcedureData:
    return MemoryProcedureData(data=await service.validate_procedure(memory_id, request))


@retrieval_router.post("", response_model=MemoryRetrievalData)
async def retrieve_memory(
    request: MemoryRetrievalRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryRetrievalData:
    return MemoryRetrievalData(data=await service.retrieve(request))


@preference_router.post("", response_model=PreferenceData, status_code=201)
async def create_preference(
    request: PreferenceCreateRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> PreferenceData:
    return PreferenceData(data=await service.create_preference(request))


@preference_router.get("", response_model=PreferenceListData)
async def list_preferences(
    service: Annotated[MemoryService, Depends(get_memory_service)],
    status: Literal["draft", "active", "revoked"] = "active",
    category: str | None = Query(default=None, max_length=100),
    keyword: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PreferenceListData:
    items, total = await service.list_preferences(
        status=status,
        category=category,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return PreferenceListData(data=items, page=page, page_size=page_size, total=total)


@preference_router.get("/{preference_id}", response_model=PreferenceData)
async def get_preference(
    preference_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> PreferenceData:
    return PreferenceData(data=await service.get_preference(preference_id))


@preference_router.patch("/{preference_id}", response_model=PreferenceData)
async def update_preference(
    preference_id: str,
    request: PreferenceUpdateRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> PreferenceData:
    return PreferenceData(data=await service.update_preference(preference_id, request))


@preference_router.post("/{preference_id}/confirm", response_model=PreferenceData)
async def confirm_preference(
    preference_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> PreferenceData:
    return PreferenceData(data=await service.confirm_preference(preference_id))


@preference_router.delete("/{preference_id}", response_model=MemoryDeleteWrapper)
async def delete_preference(
    preference_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryDeleteWrapper:
    result = await service.delete_preference(preference_id)
    return MemoryDeleteWrapper(data={"id": result["id"], "deleted": True})


__all__ = ["preference_router", "retrieval_router", "router"]
