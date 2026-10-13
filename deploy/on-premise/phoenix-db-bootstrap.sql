-- Creates Phoenix's role and database on-premise (#288, ADR 0017), as the container's superuser. deploy.sh pipes it to
-- psql after ../helm/smart-tutor/files/db-bootstrap.sql, in the same session (native-cloud doesn't run Phoenix).
-- Idempotent: every deploy runs it, and it resets the password to the Secrets Manager value, so a rotated secret or a
-- volume restored from a snapshot gets back in sync. The nightly backup leaves this database out (backup.sh).
-- psql variables: phoenix_user, phoenix_password, phoenix_db.
\set ON_ERROR_STOP on
\connect postgres

SELECT format('CREATE ROLE %I LOGIN', :'phoenix_user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'phoenix_user') \gexec
ALTER ROLE :"phoenix_user" WITH LOGIN PASSWORD :'phoenix_password';

SELECT format('CREATE DATABASE %I OWNER %I', :'phoenix_db', :'phoenix_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'phoenix_db') \gexec

-- The role connects only to its own database.
REVOKE CONNECT ON DATABASE :"phoenix_db" FROM PUBLIC;
