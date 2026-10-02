-- Runs once on an empty volume, connected to the app database (POSTGRES_DB=smart_tutor).
CREATE EXTENSION IF NOT EXISTS vector;

-- Keycloak gets its own database (PRD §9.11: separate databases for the app and Keycloak).
CREATE DATABASE keycloak;
