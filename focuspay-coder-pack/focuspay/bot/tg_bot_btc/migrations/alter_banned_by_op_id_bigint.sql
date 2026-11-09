-- Telegram user_id не помещается в int4 (max 2_147_483_647).
ALTER TABLE bot_users
    ALTER COLUMN banned_by_op_id TYPE BIGINT
    USING banned_by_op_id::bigint;
