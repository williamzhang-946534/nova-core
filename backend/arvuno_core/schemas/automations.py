from pydantic import BaseModel

from arvuno_core.automation.models import (
    AutomationCreate,
    AutomationUpdate,
    StoredAutomation,
    StoredAutomationRun,
    StoredNotification,
)


class AutomationCreateRequest(AutomationCreate):
    pass


class AutomationUpdateRequest(AutomationUpdate):
    pass


class AutomationItem(StoredAutomation):
    pass


class AutomationListData(BaseModel):
    data: list[AutomationItem]
    page: int
    page_size: int
    total: int


class AutomationDetailData(BaseModel):
    data: AutomationItem


class AutomationCreateDataWrapper(AutomationDetailData):
    pass


class AutomationUpdateDataWrapper(AutomationDetailData):
    pass


class AutomationRunItem(StoredAutomationRun):
    pass


class AutomationRunListData(BaseModel):
    data: list[AutomationRunItem]
    page: int
    page_size: int
    total: int


class NotificationItem(StoredNotification):
    pass


class NotificationListData(BaseModel):
    data: list[NotificationItem]
    page: int
    page_size: int
    total: int


class NotificationDetailData(BaseModel):
    data: NotificationItem
