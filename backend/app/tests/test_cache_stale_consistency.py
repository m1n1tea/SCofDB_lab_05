"""
LAB 05: Демонстрация неконсистентности кэша.
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
            "product_name": "Stale Product",
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
async def test_stale_order_card_when_db_updated_without_invalidation(
    client, test_order
):
    """
    TODO: Реализовать сценарий:
    1) Прогреть кэш карточки заказа (GET /api/cache-demo/orders/{id}/card?use_cache=true).
    2) Изменить заказ в БД через endpoint mutate-without-invalidation.
    3) Повторно запросить карточку с use_cache=true.
    4) Проверить, что клиент получает stale данные из кэша.
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
        f"/api/cache-demo/orders/{test_order}/mutate-without-invalidation",
        json={"new_total_amount": 250.0},
    )
    assert mutate_response.status_code == 200
    assert mutate_response.json()["cache_invalidated"] is False

    stale_response = await client.get(
        f"/api/cache-demo/orders/{test_order}/card?use_cache=true"
    )
    assert stale_response.status_code == 200
    assert stale_response.json()["total_amount"] == 100.0

    fresh_response = await client.get(
        f"/api/cache-demo/orders/{test_order}/card?use_cache=false"
    )
    assert fresh_response.status_code == 200
    assert fresh_response.json()["total_amount"] == 250.0

    await redis.delete(key)
    await redis.delete(catalog_key())
