# from typing import AsyncGenerator
# from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
# from sqlalchemy.orm import sessionmaker
# from app.core.config import settings

# # 1. Create the Async Engine
# # This requires 'asyncpg' to be installed (pip install asyncpg)
# engine = create_async_engine(
#     settings.DATABASE_URL, 
#     echo=settings.DEBUG, 
#     future=True
# )

# # 2. Create the Session Factory
# async_session_factory = sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
#     autocommit=False,
#     autoflush=False,
# )

# # 3. The Dependency
# async def get_session() -> AsyncGenerator[AsyncSession, None]:
#     """
#     FastAPI Dependency:
#     Yields an AsyncSession for the request.
#     """
#     async with async_session_factory() as session:
#         yield session




# from typing import AsyncGenerator
# from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
# from sqlalchemy.orm import sessionmaker
# from app.core.config import settings

# # Create the Async Engine with correct driver-level cache disabling
# engine = create_async_engine(
#     settings.DATABASE_URL, 
#     echo=settings.DEBUG, 
#     future=True,
#     pool_pre_ping=True, 
#     connect_args={
#         # This is the correct parameter name passed straight to the asyncpg driver
#         "prepared_statement_cache_size": 0, 
#         "server_settings": {
#             "jit": "off"  # Keeps things stable with Supabase/PgBouncer
#         }
#     }
# )

# # Cleaned up: Removed the broken `engine.dialect.statement_cache_size = 0` line

# async_session_factory = sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
#     autocommit=False,
#     autoflush=False,
# )

# async def get_session() -> AsyncGenerator[AsyncSession, None]:
#     async with async_session_factory() as session:
#         yield session


# import uuid
# from typing import AsyncGenerator
# from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
# from sqlalchemy.orm import sessionmaker
# from app.core.config import settings

# # The definitive engine configuration for Supabase Pooler + asyncpg
# engine = create_async_engine(
#     settings.DATABASE_URL, 
#     echo=settings.DEBUG, 
#     future=True,
#     pool_pre_ping=False,  # Disable SQLAlchemy's pool pre-ping (asyncpg handles this)
#     connect_args={
#         # Forces globally unique statement names to prevent PgBouncer collisions
#         # "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
#         "prepared_statement_name_func": None
#     }
# )

# async_session_factory = sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
#     autocommit=False,
#     autoflush=False,
# )

# async def get_session() -> AsyncGenerator[AsyncSession, None]:
#     async with async_session_factory() as session:
#         yield session


# import uuid
# from typing import AsyncGenerator
# from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
# from sqlalchemy.orm import sessionmaker
# from app.core.config import settings

# # 1. We format the URL to explicitly include the cache-killer query param.
# # This forces SQLAlchemy's internal initialization queries to skip statement preparation.
# db_url = settings.DATABASE_URL
# if "?" in db_url:
#     # If there's already a query parameter, append to it
#     if "prepared_statement_cache_size" not in db_url:
#         db_url += "&prepared_statement_cache_size=0"
# else:
#     db_url += "?prepared_statement_cache_size=0"

# # 2. Build the final, pooler-safe engine configuration
# engine = create_async_engine(
#     db_url, # Pass the modified URL string here
#     echo=settings.DEBUG, 
#     future=True,
#     pool_pre_ping=False, # Keeps the pool silent to avoid extra pings
#     connect_args={
#         "statement_cache_size": 0,
#         "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
#     }
# )

# async_session_factory = sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
#     autocommit=False,
#     autoflush=False,
# )

# async def get_session() -> AsyncGenerator[AsyncSession, None]:
#     async with async_session_factory() as session:
#         yield session




from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# A clean, standard engine. FastAPI will handle its own connection pool now.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_size=10,       # Number of connections to keep open
    max_overflow=20,    # Max extra connections during traffic spikes
    pool_pre_ping=True  # Safely checks if connection is alive
)

async_session_factory = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session