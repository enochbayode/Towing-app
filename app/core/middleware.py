# File: app/core/middleware.py

import asyncio
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class TimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip the timeout if the request is trying to hit your chat/ws endpoints
        if "ws" in request.url.path or request.headers.get("upgrade") == "websocket":
            return await call_next(request)

        try:
            # Wrap the entire request in a strict 60-second timer
            return await asyncio.wait_for(call_next(request), timeout=60.0)
        
        except asyncio.TimeoutError:
            print(f"KILLED STUCK REQUEST: {request.method} {request.url.path}")
            return JSONResponse(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                content={
                    "success": False, 
                    "message": "Request timed out due to slow network. Please try again."
                }
            )