"""
简易速率限制器

基于内存的滑动窗口速率限制，无外部依赖。
通过环境变量 ENGRAMA_RATE_LIMIT 控制每分钟最大请求数。

适用于单实例部署，多实例部署请使用 Redis 方案（V3+）。
"""

import asyncio
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from engrama import config
from engrama.logger import get_logger

logger = get_logger(__name__)


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """基于内存的滑动窗口速率限制中间件"""

    def __init__(self, app, max_requests_per_minute: int = 0):
        """
        Args:
            max_requests_per_minute: 每分钟最大请求数，0 表示不限制
        """
        super().__init__(app)
        self._max_rpm = max_requests_per_minute
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        """检查速率限制"""
        if self._max_rpm <= 0:
            return await call_next(request)

        # 使用 API Key 或 IP 作为限制标识
        client_id = (
            request.headers.get("X-API-Key")
            or (request.client.host if request.client else "unknown")
        )

        now = time.time()
        window_start = now - 60.0

        async with self._lock:
            # 清理过期记录
            if client_id in self._requests:
                self._requests[client_id] = [req for req in self._requests[client_id] if req > window_start]
                if not self._requests[client_id]:
                    del self._requests[client_id]

            if len(self._requests[client_id]) >= self._max_rpm:
                logger.warning("速率限制触发: client=%s, requests=%d", client_id[:16], len(self._requests[client_id]))
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "detail": f"请求过于频繁，每分钟最多 {self._max_rpm} 次请求",
                    },
                )

            self._requests[client_id].append(now)

        return await call_next(request)
