-- Run once as SYSTEM, connected to FREEPDB1.
-- Replace the password placeholder locally before executing.
-- UTILITY_GIS already exists in the completed project.

CREATE USER utility_gis
IDENTIFIED BY "REPLACE_WITH_YOUR_PROJECT_PASSWORD"
DEFAULT TABLESPACE users
TEMPORARY TABLESPACE temp
QUOTA 500M ON users;

GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW,
      CREATE SEQUENCE, CREATE PROCEDURE
TO utility_gis;