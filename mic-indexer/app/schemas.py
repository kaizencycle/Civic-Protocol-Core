from typing import Literal

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"

class IngestEvent(BaseModel):
    kind: Literal["xp_award","burn","grant","transfer"]
    amount: float = Field(gt=0)
    unit: Literal["XP","MIC"] = "XP"
    actor: str | None = None
    target: str | None = None
    meta: dict = {}

class BalanceOut(BaseModel):
    handle: str
    xp: float
    mic: float
    mic_from_xp: float
    total_mic: float

class SupplyOut(BaseModel):
    total_mic: float
    circulating_mic: float
    xp_pool: float

class EventOut(BaseModel):
    id: int
    kind: str
    amount: float
    unit: str
    actor: str | None = None
    target: str | None = None
    created_at: str
    meta: dict = {}
