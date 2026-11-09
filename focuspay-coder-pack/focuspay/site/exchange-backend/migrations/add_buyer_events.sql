-- Realtime buyer channel (SSE). ADDITIVE: new channel `web_chat_buyer`, new
-- functions + triggers. Does NOT touch the existing operator channel
-- (`web_chat_new` / notify_web_chat_new_message) or any existing trigger.
--
-- Two producers push to `web_chat_buyer`:
--   1. staff chat messages (operator/admin/system) -> buyer sees replies live
--   2. order status changes (any code path) -> buyer sees status live
--
-- Idempotent: safe to run more than once.

-- 1) Staff chat messages -> buyer. Message row has no order_id, so join the thread.
CREATE OR REPLACE FUNCTION notify_web_chat_buyer_message() RETURNS trigger AS $$
DECLARE
    v_order_id text;
BEGIN
    -- Everything that is NOT the buyer/exchanger side is a staff reply.
    IF NEW.sender_role NOT IN ('buyer', 'exchanger') THEN
        SELECT order_id INTO v_order_id
        FROM web_chat_threads
        WHERE id = NEW.thread_id;

        PERFORM pg_notify(
            'web_chat_buyer',
            json_build_object(
                'kind', 'chat',
                'thread_id', NEW.thread_id,
                'order_id', v_order_id,
                'message_id', NEW.id
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_web_chat_buyer_notify ON web_chat_messages;
CREATE TRIGGER trg_web_chat_buyer_notify
    AFTER INSERT ON web_chat_messages
    FOR EACH ROW EXECUTE FUNCTION notify_web_chat_buyer_message();

-- 2) Order status changes -> buyer. Fires only when status actually changes.
CREATE OR REPLACE FUNCTION notify_web_order_status() RETURNS trigger AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        PERFORM pg_notify(
            'web_chat_buyer',
            json_build_object(
                'kind', 'status',
                'order_id', NEW.order_id,
                'status', NEW.status
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_web_order_status_notify ON orders;
CREATE TRIGGER trg_web_order_status_notify
    AFTER UPDATE OF status ON orders
    FOR EACH ROW EXECUTE FUNCTION notify_web_order_status();
