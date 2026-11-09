-- add_chat_call_members.sql уже накатан без GRANT и второй раз не выполнится.
GRANT ALL PRIVILEGES ON TABLE chat_call_members TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE chat_call_scans TO exchange_bot;
