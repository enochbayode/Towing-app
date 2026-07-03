# # db/init_db.py
# from sqlmodel import SQLModel
# from sqlalchemy.ext.asyncio import AsyncEngine

# # Ensure the models are loaded
# import app.db.base 

# async def init_db(engine: AsyncEngine) -> None:
#     """
#     Creates all SQLModel tables in the database asynchronously.
#     """
#     async with engine.begin() as conn:
#         # Automatically builds your admin, driver, company, and user tables if they are missing
#         await conn.run_sync(SQLModel.metadata.create_all)