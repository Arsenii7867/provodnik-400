"""Pydantic-модели тел запросов и ответов. Тела запросов только через модели, чтобы в OpenAPI
не появлялись безымянные схемы Body_."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    scenarios: int
    db: str
