# from contextlib import asynccontextmanager
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from sqlmodel import SQLModel
# from arq import create_pool
# from arq.connections import RedisSettings

# # Adjust these imports based on your exact project structure
# from app.core.config import settings
# from app.core.middleware import TimeoutMiddleware 
# from app.api.v1.api import api_router

# # --- DATABASE IMPORTS ADDED HERE ---
# from app.db.session import engine

# import app.db.base  # Ensure all models are imported so they are registered with SQLModel

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     """
#     The sole lifecycle manager for your application.
#     """
#     # Startup logic: Perform initial setup here
#     print("Application is starting up...")
#     # app.state.redis = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
#     redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
#     redis_settings.ssl_cert_reqs = "none"
    
#     # Create pool with the updated settings
#     app.state.redis = await create_pool(redis_settings)
    
#     yield  # The application runs here
    
#     # Shutdown logic: Perform cleanup here
#     print("Application is shutting down...")
#     app.state.redis.close()
#     await app.state.redis.wait_closed()


from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel
from arq import create_pool
from arq.connections import RedisSettings
from urllib.parse import urlparse # <-- NEW IMPORT

from app.core.config import settings
from app.core.middleware import TimeoutMiddleware 
from app.api.v1.api import api_router
from app.db.session import engine
import app.db.base  

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application is starting up...")
    
    # 1. Parse the Upstash URL manually
    parsed_url = urlparse(settings.REDIS_URL)
    
    # 2. Force SSL to True so Upstash doesn't hang up
    redis_settings = RedisSettings(
        host=parsed_url.hostname,
        port=parsed_url.port or 6379,
        password=parsed_url.password,
        ssl=True 
    )
    
    # 3. Bypass the Windows certificate check
    redis_settings.ssl_cert_reqs = "none"
    
    app.state.redis = await create_pool(redis_settings)
    yield  
    print("Application is shutting down...")
    app.state.redis.close()
    await app.state.redis.wait_closed()


def get_application() -> FastAPI:
    """
    Application Factory Pattern.
    This creates the FastAPI application instance with all configurations.
    """
    application = FastAPI(
        title="Towing App API",
        version="1.0.0",
        debug=True,  # Set to False in production
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",  # Swagger UI
        redoc_url="/redoc",  # ReDoc UI 
        lifespan=lifespan, # <-- WE ADDED THE LIFESPAN HERE
    )

    # --- CORS MIDDLEWARE ---
    application.add_middleware(
        CORSMiddleware,
        # We completely remove allow_origins and use a catch-all regex instead. 
        # This tricks the browser/mobile app into allowing credentials from ANY origin!
        allow_origin_regex=".*", 
        allow_credentials=True, 
        allow_methods=["*"],  
        allow_headers=["*"],  
    )

    # --- TIMEOUT MIDDLEWARE ---
    # Your custom Timeout Kill Switch (ensure you have this defined in core/middleware.py)
    application.add_middleware(TimeoutMiddleware)

    # --- ROUTER REGISTRATION ---
    application.include_router(api_router, prefix="/api/v1")

    return application

app = get_application()

# --- HEALTH CHECK ---
@app.get("/", tags=["Status"])
async def root():
    return {
        "message": "Towing API is Online",
        "version": "1.0.0",
        "docs": "/docs"
    }