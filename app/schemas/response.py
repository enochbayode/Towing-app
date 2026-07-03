from typing import Generic, TypeVar, Optional
from pydantic import BaseModel

# Create a generic type variable 'T'
T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    success: bool
    message: str
    data: Optional[T] = None