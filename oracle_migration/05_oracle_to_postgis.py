from getpass import getpass

import oracledb
import psycopg


def read_lob(value):
    return value.read() if hasattr(value, "read") else value


pg_user = input("PostgreSQL username [postgres]: ").strip() or "postgres"
pg_port = int(input("PostgreSQL port [5432]: ").strip() or "5432")
oracle_password = getpass("UTILITY_GIS password: ")
pg_password = getpass("PostgreSQL password: ")

# Read a consistent snapshot directly from Oracle.
with oracledb.connect(
    user="UTILITY_GIS",
    password=oracle_password,
    dsn="localhost:1521/FREEPDB1",
) as oracle:
    with oracle.cursor() as cur:
        cur.execute("""
            SELECT osm_key, name, other_tags, source_file,
                   loaded_at, SDO_UTIL.TO_WKBGEOMETRY(geom),
                   s.geom.SDO_SRID
            FROM substation_sites s
            ORDER BY osm_key
        """)
        rows = [
            (
                key, name, read_lob(tags), source, loaded,
                read_lob(wkb), int(srid) if srid is not None else None
            )
            for key, name, tags, source, loaded, wkb, srid in cur
        ]

if len(rows) != 1309 or len({r[0] for r in rows}) != 1309:
    raise RuntimeError("Oracle count or unique-key check failed.")
if any(r[5] is None or r[6] != 4326 for r in rows):
    raise RuntimeError("Oracle geometry or SRID check failed.")

# All destination changes roll back if any check fails.
with psycopg.connect(
    host="localhost",
    port=pg_port,
    dbname="utility_migration",
    user=pg_user,
    password=pg_password,
) as pg:
    with pg.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.substation_sites (
                osm_key varchar(40) PRIMARY KEY,
                name text,
                other_tags text,
                source_file text,
                loaded_at timestamp,
                geom geometry(MultiPolygon, 4326) NOT NULL
            )
        """)

        cur.execute("SELECT COUNT(*) FROM public.substation_sites")
        if cur.fetchone()[0]:
            raise RuntimeError("Destination already contains data; stopped.")

        cur.execute("""
            CREATE TEMP TABLE oracle_snapshot (
                osm_key text PRIMARY KEY,
                name text,
                other_tags text,
                source_file text,
                loaded_at timestamp,
                wkb bytea,
                srid integer
            ) ON COMMIT DROP
        """)
        cur.executemany("""
            INSERT INTO oracle_snapshot VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, rows)

        cur.execute("""
            INSERT INTO public.substation_sites
                (osm_key, name, other_tags, source_file, loaded_at, geom)
            SELECT osm_key, name, other_tags, source_file, loaded_at,
                   ST_Multi(ST_GeomFromWKB(wkb, srid))
            FROM oracle_snapshot
        """)

        cur.execute("""
            SELECT COUNT(*),
                   COUNT(DISTINCT osm_key),
                   COUNT(*) FILTER (WHERE ST_IsValid(geom)),
                   COUNT(*) FILTER (WHERE ST_IsEmpty(geom))
            FROM public.substation_sites
        """)
        counts = cur.fetchone()
        if counts != (1309, 1309, 1309, 0):
            raise RuntimeError(f"Destination validation failed: {counts}")

        cur.execute("""
            SELECT COUNT(*)
            FROM oracle_snapshot o
            FULL JOIN public.substation_sites p USING (osm_key)
            WHERE o.osm_key IS NULL OR p.osm_key IS NULL
               OR p.name IS DISTINCT FROM o.name
               OR p.other_tags IS DISTINCT FROM o.other_tags
               OR p.source_file IS DISTINCT FROM o.source_file
               OR p.loaded_at IS DISTINCT FROM o.loaded_at
               OR ST_SRID(p.geom) IS DISTINCT FROM o.srid
               OR ST_AsBinary(p.geom, 'NDR') IS DISTINCT FROM
                  ST_AsBinary(
                      ST_Multi(ST_GeomFromWKB(o.wkb, o.srid)), 'NDR'
                  )
        """)
        if cur.fetchone()[0]:
            raise RuntimeError("Source-to-destination reconciliation failed.")

        cur.execute("""
            CREATE INDEX IF NOT EXISTS substation_sites_geom_idx
            ON public.substation_sites USING gist (geom)
        """)
        cur.execute("ANALYZE public.substation_sites")

print("COMMITTED: Oracle -> PostGIS")
print("1309 rows; 1309 unique keys; 1309 valid, nonempty geometries.")
print("0 key, attribute, timestamp, SRID, or geometry mismatches.")