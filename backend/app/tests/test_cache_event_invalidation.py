"""
LAB 05: Проверка починки через событийную инвалидацию.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infrastructure.cache_keys import catalog_key, order_card_key
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
async def test_order_card_is_fresh_after_event_invalidation(client, test_order):
    """
    TODO: Реализовать сценарий:
    1) Прогреть кэш карточки заказа.
    2) Изменить заказ через mutate-with-event-invalidation.
    3) Убедиться, что ключ карточки инвалидирован.
    4) Повторный GET возвращает свежие данные из БД, а не stale cache.
    """

    redis = get_redis()
    key = order_card_key(str(test_order))
    await redis.delete(key)
    await redis.delete(catalog_key())

    warm_response = await client.get(
        f"/api/cache-demo/orders/{test_order}/card?use_cache=true"
    )
    assert warm_response.status_code == 200
    assert warm_response.json()["total_amount"] == 100.0
    assert await redis.get(key) is not None

    mutate_response = await client.post(
        f"/api/cache-demo/orders/{test_order}/mutate-with-event-invalidation",
        json={"new_total_amount": 300.0},
    )
    assert mutate_response.status_code == 200
    assert mutate_response.json()["cache_invalidated"] is True
    assert await redis.get(key) is None

    fresh_response = await client.get(
        f"/api/cache-demo/orders/{test_order}/card?use_cache=true"
    )
    assert fresh_response.status_code == 200
    assert fresh_response.json()["total_amount"] == 300.0

    cache_response = await client.get(
        f"/api/cache-demo/orders/{test_order}/card?use_cache=true"
    )
    assert cache_response.status_code == 200
    assert cache_response.json()["total_amount"] == 300.0

    await redis.delete(key)
    await redis.delete(catalog_key())
