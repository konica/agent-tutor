-- Creates the app and Keycloak roles and databases on RDS (#57), connected as the master user to `postgres`.
-- Idempotent: every Helm install and upgrade runs it, and it resets the passwords to the Secrets Manager values,
-- so a rotated secret or an instance restored from a snapshot gets back in sync. Running Keycloak pods keep the
-- old password until restarted (rotation steps: docs/runbooks/pilot-deploy.md).
-- psql variables: app_user, app_password, app_db, keycloak_user, keycloak_password, keycloak_db.
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I LOGIN', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec
SELECT format('CREATE ROLE %I LOGIN', :'keycloak_user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'keycloak_user') \gexec
ALTER ROLE :"app_user" WITH LOGIN PASSWORD :'app_password';
ALTER ROLE :"keycloak_user" WITH LOGIN PASSWORD :'keycloak_password';

-- The RDS master is not a superuser: since PostgreSQL 16 it may create a database owned by a role only as a member.
GRANT :"app_user" TO CURRENT_USER;
GRANT :"keycloak_user" TO CURRENT_USER;

SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_db') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'keycloak_db', :'keycloak_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'keycloak_db') \gexec

-- Each role connects only to its own database.
REVOKE CONNECT ON DATABASE :"app_db" FROM PUBLIC;
REVOKE CONNECT ON DATABASE :"keycloak_db" FROM PUBLIC;

-- pgvector needs rds_superuser, which the app role does not have (the same as local/postgres/init/01-init.sql).
\connect :"app_db"
CREATE EXTENSION IF NOT EXISTS vector;
