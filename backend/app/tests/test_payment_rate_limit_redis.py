"""
LAB 05: Rate limiting endpoint оплаты через Redis.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infrastructure.cache_keys import payment_rate_limit_key
from app.infrastructure.db import get_db
from app.infrastructure.redis_client import get_redis
from app.main import app

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@db:5432/marketplace"


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.fixture
async def db_engine():
    engine = create_async_engine(DATABASE_URL, echo=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    async with AsyncSession(db_engine) as session:
        yield session


@pytest.fixture
async def test_order(db_session):
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()
    item_id = uuid.uuid4()
    status_history_id = uuid.uuid4()

    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, name, created_at)
            VALUES (:id, :email, :name, NOW())
            """
        ),
        {
            "id": user_id,
            "email": f"test_order_{uuid.uuid4()}@example.com",
            "name": "Test User",
        },
    )

    await db_session.execute(
        text(
            """
            INSERT INTO orders (id, user_id, status, total_amount, created_at)
            VALUES (:id, :user_id, :status, 100.00, NOW())
            """
        ),
        {"id": order_id, "user_id": user_id, "status": "created"},
    )

    await db_session.execute(
        text(
            """
            INSERT INTO order_items (id, order_id, product_name, price, quantity)
            VALUES (:id, :order_id, :product_name, :price, :quantity)
            """
        ),
        {
            "id": item_id,
            "order_id": order_id,
            "product_name": "Event Product",
            "price": 100.0,
            "quantity": 1,
        },
    )

    await db_session.execute(
        text(
            """
            INSERT INTO order_status_history (id, order_id, status, changed_at)
            VALUES (:id, :order_id, :status, NOW())
            """
        ),
        {
            "id": status_history_id,
            "order_id": order_id,
            "status": "created",
        },
    )

    await db_session.commit()
    yield order_id

    await db_session.rollback()

    await db_session.execute(
        text("DELETE FROM order_status_history WHERE order_id = :order_id"),
        {"order_id": order_id},
    )
    await db_session.execute(
        text("DELETE FROM order_items WHERE order_id = :order_id"),
        {"order_id": order_id},
    )
    await db_session.execute(
        text("DELETE FROM orders WHERE id = :order_id"),
        {"order_id": order_id},
    )
    await db_session.execute(
        text("DELETE FROM users WHERE id = :user_id"),
        {"user_id": user_id},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_payment_endpoint_rate_limit(client, test_order):
    """
    Рекомендуемая проверка:
    1) Сделать N запросов оплаты в пределах одного окна.
    2) Проверить, что первые <= limit проходят.
    3) Следующие запросы получают 429 Too Many Requests.
    4) Проверить заголовки X-RateLimit-Limit / X-RateLimit-Remaining.
    """
    redis = get_redis()
    subject = "rate-limit-user"
    key = payment_rate_limit_key(subject)
    await redis.delete(key)

    headers = {"X-User-Id": subject}
    statuses: list[int] = []
    responses = []

    order_id = test_order
    for _ in range(6):
        response = await client.post(
            "/api/payments/retry-demo",
            headers=headers,
            json={"order_id": str(order_id), "mode": "unsafe"},
        )
        statuses.append(response.status_code)
        responses.append(response)

    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert statuses[5] == 429

    first = responses[0]
    assert first.headers["X-RateLimit-Limit"] == "5"
    assert first.headers["X-RateLimit-Remaining"] == "4"

    second = responses[1]
    assert second.headers["X-RateLimit-Limit"] == "5"
    assert second.headers["X-RateLimit-Remaining"] == "3"

    last_nonblocked = responses[4]
    assert last_nonblocked.headers["X-RateLimit-Limit"] == "5"
    assert last_nonblocked.headers["X-RateLimit-Remaining"] == "0"

    blocked = responses[5]
    assert blocked.headers["X-RateLimit-Limit"] == "5"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.json()["detail"] == "Too Many Requests"

    await redis.delete(key)
