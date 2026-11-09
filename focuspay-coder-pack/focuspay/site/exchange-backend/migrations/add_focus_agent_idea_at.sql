-- When Focus Agent last asked a user chat for ideas. Idempotent.

ALTER TABLE focus_agent_chats
    ADD COLUMN IF NOT EXISTS last_idea_at TIMESTAMPTZ;
