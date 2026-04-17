"""Cache service implementation for LAB 05."""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.cache_keys import catalog_key, order_card_key
from app.infrastructure.redis_client import get_redis

CATALOG_CACHE_TTL_SECONDS = 60
ORDER_CARD_CACHE_TTL_SECONDS = 60


class CacheService:
    """
    Сервис кэширования каталога и карточки заказа.

    TODO:
    - реализовать методы через Redis client + БД;
    - добавить TTL и версионирование ключей.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.redis = get_redis()

    async def get_catalog(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        """
        TODO:
        1) Попытаться вернуть catalog из Redis.
        2) При miss загрузить из БД.
        3) Положить в Redis с TTL.
        """
        key = catalog_key()

        if use_cache:
            try:
                cached_payload = await self.redis.get(key)
                if cached_payload:
                    return json.loads(cached_payload)
            except Exception:
                # Graceful fallback to DB if Redis is unavailable.
                pass

        catalog = await self._load_catalog_from_db()

        if use_cache:
            try:
                await self.redis.setex(
                    key, CATALOG_CACHE_TTL_SECONDS, json.dumps(catalog)
                )
            except Exception:
                pass

        return catalog

    async def get_order_card(
        self,
        order_id: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """
        TODO:
        1) Попытаться вернуть карточку заказа из Redis.
        2) При miss загрузить из БД.
        3) Положить в Redis с TTL.
        """
        key = order_card_key(order_id)

        if use_cache:
            try:
                cached_payload = await self.redis.get(key)
                if cached_payload:
                    return json.loads(cached_payload)
            except Exception:
                pass

        order_card = await self._load_order_card_from_db(order_id)
        if order_card is None:
            return {}

        if use_cache:
            try:
                await self.redis.setex(
                    key, ORDER_CARD_CACHE_TTL_SECONDS, json.dumps(order_card)
                )
            except Exception:
                pass

        return order_card

    async def invalidate_order_card(self, order_id: str) -> None:
        """TODO: Удалить ключ карточки заказа из Redis."""
        try:
            await self.redis.delete(order_card_key(order_id))
        except Exception:
            pass

    async def invalidate_catalog(self) -> None:
        """TODO: Удалить ключ каталога из Redis."""
        try:
            await self.redis.delete(catalog_key())
        except Exception:
            pass

    async def _load_catalog_from_db(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            text(
                """
                SELECT
                    oi.product_name,
                    sum(oi.quantity) AS sold_qty,
                    round(avg(oi.price), 2) AS avg_price
                FROM order_items oi
                GROUP BY oi.product_name
                """
            )
        )

        catalog: list[dict[str, Any]] = []
        for row in result.mappings():
            catalog.append(
                {
                    "product_name": row["product_name"],
                    "sold_qty": int(row["sold_qty"] or 0),
                    "avg_price": float(row["avg_price"] or 0),
                }
            )
        return catalog

    async def _load_order_card_from_db(self, order_id: str) -> dict[str, Any] | None:
        order_result = await self.db.execute(
            text(
                """
                SELECT id, user_id, status, total_amount, created_at
                FROM orders
                WHERE id = :order_id
                """
            ),
            {"order_id": str(order_id)},
        )
        order_row = order_result.mappings().first()
        if order_row is None:
            return None

        items_result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    product_name,
                    price,
                    quantity,
                    (price * quantity) AS subtotal
                FROM order_items
                WHERE order_id = :order_id
                ORDER BY product_name
                """
            ),
            {"order_id": str(order_id)},
        )

        items: list[dict[str, Any]] = []
        for row in items_result.mappings():
            items.append(
                {
                    "id": str(row["id"]),
                    "product_name": row["product_name"],
                    "price": float(row["price"]),
                    "quantity": int(row["quantity"]),
                    "subtotal": float(row["subtotal"]),
                }
            )

        return {
            "id": str(order_row["id"]),
            "user_id": str(order_row["user_id"]),
            "status": order_row["status"],
            "total_amount": float(order_row["total_amount"]),
            "created_at": str(order_row["created_at"]),
            "items": items,
        }
