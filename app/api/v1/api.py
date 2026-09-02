from fastapi import APIRouter

from app.api.v1.endpoints import auth, admin, driver, company, trip, webhook, vehicle, courier

api_router = APIRouter()

# Include all endpoint routers here with their respective prefixes and tags

# Auth routes
api_router.include_router(
    auth.router, 
    prefix="/auth", 
    tags=["Authentication"]
)

# Admin routes
api_router.include_router(
    admin.router,
    prefix="/admin",
    tags=["Admin endpoints"]
)

# Driver routes
api_router.include_router(
    driver.router,
    prefix="/driver",
    tags=["Driver endpoints"]
)

# Comapany routes
api_router.include_router(
    company.router,
    prefix="/company",
    tags=["Company endpoints"]
)

# Trip routes
api_router.include_router(
    trip.router,
    prefix="/trip",
    tags=["Trip endpoints"]
)

# vehicle endpoints
# api_router.include_router(
#     vehicle.router,
#     prefix="/vehicle",
#     tags=["Comapany's vehicle endpoints"]
# )

# Webhook routes (no prefix, as these are called by external services)
api_router.include_router(
    webhook.router, 
    prefix="/paystack-webhook", 
    tags=["webhooks"]
)

api_router.include_router(
    courier.router,
    prefix="/courier", 
    tags=["Courier endpoints"]
)