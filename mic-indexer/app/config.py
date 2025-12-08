from pydantic import BaseModel
import os

class Settings(BaseModel):
    DB_URL: str = os.getenv("MIC_DB_URL", "sqlite:///./mic.db")
    API_KEY: str | None = os.getenv("MIC_API_KEY")
    XP_TO_MIC_RATIO: float = float(os.getenv("MIC_XP_TO_MIC_RATIO", "0.001"))
    CORS_ALLOW_ORIGINS: str = os.getenv("CORS_ALLOW_ORIGINS", "*")

settings = Settings()
