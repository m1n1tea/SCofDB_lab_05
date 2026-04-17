# Лабораторная работа №5
## Redis-кэш, консистентность данных и rate limiting

## Важное уточнение
ЛР5 является **продолжением ЛР4/ЛР3/ЛР2** и выполняется на том же проекте.

В `lab_05` уже лежит кодовая база из предыдущей лабораторной:
- `backend/`
- `frontend/`
- Docker-инфраструктура
- ранее реализованные механизмы (включая сценарии оплаты)

## Цель работы
Реализовать и исследовать:
1. Redis-кэш для каталога товаров и карточки заказа.
2. Намеренно сломанный сценарий консистентности:
   - изменить заказ в БД,
   - не инвалидировать кэш,
   - показать stale data для пользователя.
3. Починку через корректную инвалидацию по событию.
4. Rate limiting endpoint оплаты через Redis
   (защита от DDoS и случайных двойных кликов).
5. Замеры RPS до/после кэша через `wrk` или `locust`.

## Что дано готовым
1. Redis в `docker-compose.yml`.
2. Шаблоны backend:
   - `backend/app/infrastructure/redis_client.py`
   - `backend/app/infrastructure/cache_keys.py`
   - `backend/app/middleware/rate_limit_middleware.py`
   - `backend/app/api/cache_demo_routes.py`
   - `backend/app/application/cache_service.py`
   - `backend/app/application/cache_events.py`
3. Шаблон миграции:
   - `backend/migrations/003_cache_invalidation_events.sql` (опционально)
4. Шаблоны тестов:
   - `backend/app/tests/test_cache_stale_consistency.py`
   - `backend/app/tests/test_cache_event_invalidation.py`
   - `backend/app/tests/test_payment_rate_limit_redis.py`
5. Шаблоны нагрузочного тестирования:
   - `loadtest/wrk/*.lua`
   - `loadtest/locustfile.py`

## Что нужно реализовать (TODO)

### 1) Redis-кэш каталога и карточки заказа
Файлы:
- `backend/app/api/cache_demo_routes.py`
- `backend/app/application/cache_service.py`

Требования:
- кэш `catalog`;
- кэш `order card` по `order_id`;
- TTL для кэша;
- поддержка режима `use_cache=true/false` для сравнения в бенчмарках.

### 2) Намеренно сломанная консистентность
Файл:
- `backend/app/api/cache_demo_routes.py` (`mutate-without-invalidation`)

Нужно показать:
1. кэш прогрет;
2. заказ изменён в БД;
3. кэш не инвалидирован;
4. клиент видит устаревшие данные.

### 3) Починка через событийную инвалидацию
Файлы:
- `backend/app/application/cache_events.py`
- `backend/app/api/cache_demo_routes.py` (`mutate-with-event-invalidation`)
- `backend/app/application/cache_service.py`
- (опционально) `backend/migrations/003_cache_invalidation_events.sql`

Требования:
- при событии изменения заказа инвалидировать связанные ключи:
  - `order_card:v1:{order_id}`
  - `catalog:v1` (если затрагивается агрегат каталога).

### 4) Rate limiting endpoint оплаты через Redis
Файл:
- `backend/app/middleware/rate_limit_middleware.py`

Требования:
- ограничение частоты на endpoint оплаты;
- при превышении — `429 Too Many Requests`;
- заголовки лимита (например `X-RateLimit-*`).

### 5) Замеры RPS до/после кэша
Файлы:
- `loadtest/wrk/catalog.lua`
- `loadtest/wrk/order_card.lua`
- `loadtest/locustfile.py`

Нужно сравнить:
1. `use_cache=false` (или отключённый кэш);
2. `use_cache=true` (прогретый Redis);
3. RPS/latency/error rate.

## Запуск
```bash
cd lab_05
docker compose down -v
docker compose up -d --build
```

Проверка:
- Backend: `http://localhost:8082/health`
- Frontend: `http://localhost:5174`
- PostgreSQL: `localhost:5434`
- Redis: `localhost:6380`

## Рекомендуемый порядок выполнения
```bash
# 1) Подготовить данные для demo
docker compose exec -T db psql -U postgres -d marketplace -f /sql/01_prepare_demo_order.sql
docker compose exec -T db psql -U postgres -d marketplace -c 'SELECT * FROM orders;'
# 2) Реализовать кэш и demo endpoints
# backend/app/api/cache_demo_routes.py
# backend/app/application/cache_service.py

# 3) Реализовать rate limiting middleware
# backend/app/middleware/rate_limit_middleware.py

# 4) Реализовать тесты LAB 05
docker compose exec -T backend pytest app/tests/test_cache_stale_consistency.py -v -s
docker compose exec -T backend pytest app/tests/test_cache_event_invalidation.py -v -s
docker compose exec -T backend pytest app/tests/test_payment_rate_limit_redis.py -v -s

# 5) Запустить нагрузочные тесты
wrk -t4 -c100 -d30s -s loadtest/wrk/catalog.lua http://localhost:8082
wrk -t4 -c100 -d30s -s loadtest/wrk/order_card.lua http://localhost:8082
```

## Структура LAB 05
```
lab_05/
├── backend/
│   ├── app/
│   │   ├── api/cache_demo_routes.py
│   │   ├── application/cache_service.py
│   │   ├── application/cache_events.py
│   │   ├── middleware/rate_limit_middleware.py
│   │   └── tests/
│   │       ├── test_cache_stale_consistency.py
│   │       ├── test_cache_event_invalidation.py
│   │       └── test_payment_rate_limit_redis.py
│   └── migrations/
│       └── 003_cache_invalidation_events.sql
├── loadtest/
│   ├── wrk/catalog.lua
│   ├── wrk/order_card.lua
│   └── locustfile.py
├── sql/
│   ├── 01_prepare_demo_order.sql
│   ├── 02_check_order_card_source.sql
│   └── 03_catalog_source_query.sql
├── REPORT.md
└── README.md
```

## Критерии оценки
- Реализация Redis-кэша и демонстрация stale data — 30%
- Починка через событийную инвалидацию — 25%
- Redis rate limiting на оплате — 20%
- Бенчмарки RPS до/после кэша — 15%
- Качество отчёта и выводов — 10%
