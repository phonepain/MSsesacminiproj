# schema.py
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class Activity(BaseModel):
    time: str = Field(description="HH:MM 형식의 시간")
    description: str = Field(description="활동 내용 설명")
    location: Optional[str] = Field(None, description="장소명")
    lat: float = Field(default=0.0, description="위도 (필수)")
    lng: float = Field(default=0.0, description="경도 (필수)")
    transport: Optional[str] = Field(None, description="이동 수단 정보")
    sub_mode: Optional[Literal["subway", "bus"]] = None

class PlanUpdate(BaseModel):
    action: Literal["add", "remove", "replace", "clear", "set_activities"]
    day: int
    activities: Optional[List[Activity]] = None
    activity: Optional[Activity] = None

class FinalResponse(BaseModel):
    """최종 프론트엔드 응답 규격"""
    response: str = Field(description="사용자에게 전달할 자연어 답변")
    planUpdates: List[PlanUpdate] = Field(default_factory=list)