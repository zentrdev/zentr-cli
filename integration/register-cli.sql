-- Scoped registration only. No existing clients or callbacks are modified.
INSERT INTO oauth_clients (client_id, name, redirect_uris)
VALUES ('zentr-cli', 'Zentr CLI', '["http://localhost:8787/oauth/callback"]')
ON CONFLICT(client_id) DO NOTHING;
