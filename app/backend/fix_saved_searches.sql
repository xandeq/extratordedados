-- Fix para /api/client/saved-searches → 500 Internal Server Error
-- CAUSA: Tabela 'saved_searches' não existe no schema do PostgreSQL.
-- INSTRUÇÃO: Execute este SQL no PostgreSQL da VPS após restaurar o SSH.
--
-- Conexão: psql -U extrator -d extrator -h localhost
-- Ou via Docker: docker exec -it <postgres_container> psql -U extrator -d extrator

CREATE TABLE IF NOT EXISTS saved_searches (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    filters JSONB NOT NULL DEFAULT '{}',
    notify_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    notify_email VARCHAR(255),
    last_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_searches_user_id ON saved_searches(user_id);

-- Confirmar criação
SELECT COUNT(*) as total_saved_searches FROM saved_searches;
