-- ════════════════════════════════════════════════════════════════════════════════
-- ALTER TABLE: EXPANSÃO DA TABELA LEADS (Database-First Model)
-- Adiciona colunas para validação, enriquecimento e qualificação de leads
-- ════════════════════════════════════════════════════════════════════════════════

-- Versão do schema
ALTER TABLE leads ADD COLUMN IF NOT EXISTS schema_version VARCHAR(10) DEFAULT '3.0';

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNA 1: Identificação única para deduplicação
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS company_slug VARCHAR(255) UNIQUE;
-- Preenchida com slug(company_name): "clinica-vitoria-saude"

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNAS 2-4: Endereço Completo (CRÍTICO)
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS zip_code VARCHAR(8);
-- CEP: "29000000"

ALTER TABLE leads ADD COLUMN IF NOT EXISTS neighborhood VARCHAR(255);
-- Bairro: "Praia do Canto"

ALTER TABLE leads ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255);
-- Razão social (de CNPJ)

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNAS 5-6: Geolocalização (para mapas e análise)
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS latitude DECIMAL(10,8);
-- -20.31936
ALTER TABLE leads ADD COLUMN IF NOT EXISTS longitude DECIMAL(11,8);
-- -40.32765

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNAS 7-9: Validações de Contato
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;
-- Validado via SMTP check ou API

ALTER TABLE leads ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN DEFAULT FALSE;
-- Validado via regex ou API

ALTER TABLE leads ADD COLUMN IF NOT EXISTS website_verified BOOLEAN DEFAULT FALSE;
-- Website acessível e respondendo

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNA 10: Informações de Redes Sociais Expandidas
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS social_instagram_followers INT DEFAULT 0;
-- Número de seguidores no Instagram

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNA 11: Horário de Funcionamento (JSONB)
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS business_hours JSONB;
-- {"mon": "09:00-18:00", "tue": "09:00-18:00", "wed": "09:00-18:00", "thu": "09:00-18:00", "fri": "09:00-18:00", "sat": null, "sun": null}

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNA 12-14: Informações da Empresa
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS employee_count VARCHAR(50);
-- "1-10", "11-50", "51-100", "100+"

ALTER TABLE leads ADD COLUMN IF NOT EXISTS founded_year INT;
-- Ano de fundação: 2015

ALTER TABLE leads ADD COLUMN IF NOT EXISTS description TEXT;
-- Descrição da empresa

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNA 15: Sub-nicho/Especialidade
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS sub_niche VARCHAR(255);
-- "Cardiologia", "Apartamentos", "Tributária"

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNAS 16-17: Qualidade e Completude (NOVO SISTEMA)
-- ────────────────────────────────────────────────────────────────────────────────

-- IMPORTANTE: quality_score já existe como VARCHAR, vou deixar para não quebrar compatibilidade
-- Vou adicionar quality_score_numeric para o novo sistema

ALTER TABLE leads ADD COLUMN IF NOT EXISTS quality_score_numeric INT DEFAULT 0;
-- Novo campo numérico (0-100) para substituir o VARCHAR anterior
-- 0-30: Bronze (email only)
-- 31-60: Silver (email + phone)
-- 61-80: Gold (email + phone + address)
-- 81-100: Platinum (ultra-completo)

ALTER TABLE leads ADD COLUMN IF NOT EXISTS completeness_pct INT DEFAULT 0;
-- % de campos preenchidos (0-100)

ALTER TABLE leads ADD COLUMN IF NOT EXISTS confidence_level VARCHAR(20) DEFAULT 'low';
-- low, medium, high (baseado em validação + sources)

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNA 18: Rastreamento de Origem dos Dados (JSONB)
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS data_sources JSONB;
-- ["google_maps", "website_scrape", "hunter.io", "brasilapi", "nominatim"]

-- ────────────────────────────────────────────────────────────────────────────────
-- COLUNA 19-20: Timestamps de Scraping/Verificação
-- ────────────────────────────────────────────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS first_scraped_at TIMESTAMP;
-- Quando foi scrapado pela primeira vez

ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP;
-- Última verificação/validação

-- ────────────────────────────────────────────────────────────────────────────────
-- ÍNDICES para Performance
-- ────────────────────────────────────────────────────────────────────────────────

-- Índice composto para busca por nicho + cidade + qualidade
CREATE INDEX IF NOT EXISTS idx_leads_niche_city_quality
ON leads(niche, city, quality_score_numeric DESC);

-- Índice para busca por CEP
CREATE INDEX IF NOT EXISTS idx_leads_zip_code
ON leads(zip_code);

-- Índice para buscas geográficas
CREATE INDEX IF NOT EXISTS idx_leads_coordinates
ON leads(latitude, longitude) WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Índice para leads verificados
CREATE INDEX IF NOT EXISTS idx_leads_verified
ON leads(email_verified, phone_verified, website_verified);

-- Índice para qualidade_score_numeric
CREATE INDEX IF NOT EXISTS idx_leads_quality_numeric
ON leads(quality_score_numeric DESC);

-- Índice para company_slug (dedup)
CREATE INDEX IF NOT EXISTS idx_leads_company_slug
ON leads(company_slug);

-- Índice para last_verified_at (para encontrar leads antigos)
CREATE INDEX IF NOT EXISTS idx_leads_last_verified
ON leads(last_verified_at DESC);

-- ════════════════════════════════════════════════════════════════════════════════
print '✅ ALTER TABLE completed successfully!';
print 'New columns added for Database-First model:';
print '  - Geolocation: zip_code, neighborhood, latitude, longitude';
print '  - Validation: email_verified, phone_verified, website_verified';
print '  - Quality: quality_score_numeric, completeness_pct, confidence_level';
print '  - Sources: data_sources (JSONB)';
print '  - Company Info: legal_name, employee_count, founded_year, description, sub_niche';
print '  - Business: business_hours (JSONB), social_instagram_followers';
print '  - Dedup: company_slug (UNIQUE)';
print '  - Timestamps: first_scraped_at, last_verified_at';
