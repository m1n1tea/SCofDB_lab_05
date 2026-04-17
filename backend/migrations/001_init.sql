CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE order_statuses (
    status VARCHAR(50) PRIMARY KEY,
    description TEXT
);

INSERT INTO order_statuses (status, description) VALUES
    ('created', 'Заказ создан'),
    ('paid', 'Заказ оплачен'),
    ('cancelled', 'Заказ отменен'),
    ('shipped', 'Заказ отправлен'),
    ('completed', 'Заказ завершен');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT users_email_unique UNIQUE (email),
    CONSTRAINT users_email_not_empty CHECK (email <> ''),
    CONSTRAINT users_email_valid CHECK (email ~ '^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+$')
);

CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    total_amount NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_orders_status FOREIGN KEY (status) REFERENCES order_statuses(status),
    CONSTRAINT orders_total_amount_positive CHECK (total_amount >= 0)
);

CREATE TABLE order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    quantity INT NOT NULL,
    CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT order_items_price_positive CHECK (price >= 0),
    CONSTRAINT order_items_quantity_positive CHECK (quantity > 0),
    CONSTRAINT order_items_product_name_not_empty CHECK (product_name <> '')
);


CREATE TABLE order_status_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL,
    status VARCHAR(50) NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_history_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT fk_history_status FOREIGN KEY (status) REFERENCES order_statuses(status)
);


CREATE OR REPLACE FUNCTION check_order_not_already_paid()
RETURNS TRIGGER AS $$
BEGIN
    -- Проверяем только если новый статус = 'paid'
    IF NEW.status = 'paid' THEN
        -- Если в истории уже есть запись со статусом 'paid' для этого заказа
        IF EXISTS (
            SELECT 1
            FROM order_status_history
            WHERE order_id = NEW.id AND status = 'paid'
        ) THEN
            RAISE EXCEPTION 'Заказ уже был оплачен ранее. Повторная оплата невозможна.';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_check_order_not_already_paid
    BEFORE UPDATE ON orders FOR EACH ROW
    EXECUTE FUNCTION check_order_not_already_paid();
