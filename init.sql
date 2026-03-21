-- PostgreSQL initialization script.
-- Mounted into container at /docker-entrypoint-initdb.d/init.sql
-- Runs once on first database creation.

CREATE EXTENSION IF NOT EXISTS vector;
