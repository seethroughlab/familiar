-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable trigram similarity (used for fuzzy artist matching)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
