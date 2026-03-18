"""Common Pydantic schemas shared across route modules."""

from pydantic import BaseModel


class CancelResponse(BaseModel):
    """Response for cancel operations."""

    status: str
    message: str
    requested: bool = True
