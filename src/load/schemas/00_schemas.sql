-- src/load/schemas/00_schemas.sql
-- Schema namespaces only. 
-- NOTE: CREATE EXTENSION postgis lives in deploy/postgres/init/001_enable_postgis.sql (cluster-level, runs once).
-- So file is safe to re-run against a non-Docker Postgres too.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS atmotube;
CREATE SCHEMA IF NOT EXISTS fitbit;
-- CREATE SCHEMA IF NOT EXISTS timeline; -- google maps timeline 