# # app/api/v1/endpoints/vehicle.py
# from fastapi import APIRouter, Depends, HTTPException, status
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlmodel import select
# from uuid import UUID
# from sqlalchemy.exc import IntegrityError

# from app.db.session import get_session
# from app.models.vehicle import Vehicle 
# from app.schemas.vehicle import VehicleCreate, VehicleUpdate
# from app.schemas.user import APIResponse
# from app.models.admin import Admin
# from app.api.deps import get_current_admin

# router = APIRouter()

