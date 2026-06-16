from pydantic import BaseModel
from typing import Optional
from app.models.enums import QueryMode


class AssistantQueryRequest(BaseModel):
    query_text: str
    mode: Optional[QueryMode] = QueryMode.chat


class AssistantQueryResponse(BaseModel):
    id: str | None = None
    type: str
    content: str
    mode: str
    success: bool
    degraded: bool = False
    sql: str | None = None
    executionTime: str | None = None
    execution_time: str | None = None
    data: list[dict] | None = None
    rowCount: int | None = None
