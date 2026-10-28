from pydantic import BaseModel, Field

from nova_core.tasks.models import StoredTask, StoredTaskDetail, TaskCreate


class TaskCreateRequest(TaskCreate):
    pass


class TaskItem(StoredTask):
    pass


class TaskDetailData(StoredTaskDetail):
    pass


class TaskCreateData(TaskDetailData):
    confirmation_token: str | None = Field(default=None, max_length=512)


class TaskListData(BaseModel):
    data: list[TaskItem]
    page: int
    page_size: int
    total: int


class TaskDetailDataWrapper(BaseModel):
    data: TaskDetailData


class TaskCreateDataWrapper(BaseModel):
    data: TaskCreateData


class TaskConfirmRequest(BaseModel):
    confirmed: bool
    confirmation_token: str = Field(min_length=1, max_length=512)


class TaskCancelRequest(BaseModel):
    reason: str = Field(default="Cancelled by the user.", max_length=500)
