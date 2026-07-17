-- deploy/postgres/init/001_enable_postgis.sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT postgis_full_version();   