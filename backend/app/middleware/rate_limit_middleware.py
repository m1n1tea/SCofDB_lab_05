"""Rate limiting middleware template for LAB 05."""

import re
from typing import Callable

from fastapi import Request, Response
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.infrastructure.cache_keys import payment_rate_limit_key
from app.infrastructure.redis_client import get_redis


ORDER_PAY_PATH_RE = re.compile(r"^/api/orders/[0-9a-fA-F-]+/pay$")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-based rate limiting для endpoint оплаты.

    Цель:
    - защита от DDoS/шторма запросов;
    - защита от случайных повторных кликов пользователя.
    """

    def __init__(self, app, limit_per_window: int = 5, window_seconds: int = 10):
        super().__init__(app)
        self.limit_per_window = limit_per_window
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        TODO: Реализовать Redis rate limiting.

        Рекомендуемая логика:
        1) Применять только к endpoint оплаты:
           - /api/orders/{order_id}/pay
           - /api/payments/retry-demo
        2) Сформировать subject:
           - user_id (если есть), иначе client IP.
        3) Использовать Redis INCR + EXPIRE:
           - key = rate_limit:pay:{subject}
           - если counter > limit_per_window -> 429 Too Many Requests.
        4) Для прохождения запроса добавить в ответ headers:
           - X-RateLimit-Limit
           - X-RateLimit-Remaining
        """

        if request.method != "POST":
            return await call_next(request)

        path = request.url.path
        is_payment_endpoint = path == "/api/payments/retry-demo" or ORDER_PAY_PATH_RE.match(path)
        if not is_payment_endpoint:
            return await call_next(request)

        subject = request.headers.get("X-User-Id")
        if not subject:
            subject = request.client.host if request.client else "anonymous"

        key = payment_rate_limit_key(subject)
        redis = get_redis()

        try:
            counter = await redis.incr(key)
            if counter == 1:
                await redis.expire(key, self.window_seconds)
            ttl = await redis.ttl(key)
        except Exception:
            return await call_next(request)

        remaining = max(self.limit_per_window - counter, 0)
        reset_after = ttl if ttl >= 0 else self.window_seconds
        headers = {
            "X-RateLimit-Limit": str(self.limit_per_window),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_after),
        }

        if counter > self.limit_per_window:
            headers["Retry-After"] = str(reset_after)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests"},
                headers=headers,
            )

        response = await call_next(request)
        for header_name, header_value in headers.items():
            response.headers[header_name] = header_value

        return response
