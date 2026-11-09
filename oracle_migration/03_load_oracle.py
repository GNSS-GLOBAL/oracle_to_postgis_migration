import json
from pathlib import Path
from getpass import getpass

import oracledb

source = Path(__file__).resolve().parent / "substations_oracle.json"
features = json.loads(source.read_text(encoding="utf-8-sig"))["features"]

# Check the payload before changing the database.
keys = [f["properties"].get("osm_key") for f in features]

if len(features) != 1309:
    raise ValueError(f"Expected 1309 features; found {len(features)}")
if any(not k or k in ("way/", "relation/") for k in keys):
    raise ValueError("Missing or incomplete source keys")
if len(set(keys)) != len(keys):
    raise ValueError("Duplicate source keys")
if any(
    not f.get("geometry")
    or f["geometry"]["type"] not in ("Polygon", "MultiPolygon")
    for f in features
):
    raise ValueError("Missing or unexpected geometry type")

with oracledb.connect(
    user="UTILITY_GIS",
    password=getpass("UTILITY_GIS password: "),
    dsn="localhost:1521/FREEPDB1",
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM user_tables
            WHERE table_name = 'SUBSTATION_SITES'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                CREATE TABLE substation_sites (
                    osm_key VARCHAR2(40 CHAR) PRIMARY KEY,
                    name VARCHAR2(1000 CHAR),
                    other_tags CLOB,
                    geom MDSYS.SDO_GEOMETRY,
                    source_file VARCHAR2(100 CHAR)
                        DEFAULT 'arizona-261107.osm.pbf',
                    loaded_at TIMESTAMP DEFAULT SYSTIMESTAMP
                )
            """)

        cursor.execute("SELECT COUNT(*) FROM substation_sites")
        if cursor.fetchone()[0] != 0:
            raise RuntimeError("Table already contains data; stopping safely.")

        rows = [
            {
                "osm_key": f["properties"]["osm_key"],
                "name": f["properties"].get("name"),
                "tags": f["properties"].get("other_tags"),
                "geometry": json.dumps(f["geometry"]),
            }
            for f in features
        ]

        cursor.setinputsizes(
            osm_key=40,
            name=1000,
            tags=oracledb.DB_TYPE_CLOB,
            geometry=oracledb.DB_TYPE_CLOB,
        )

        try:
            cursor.executemany("""
                INSERT INTO substation_sites
                    (osm_key, name, other_tags, geom)
                VALUES (
                    :osm_key, :name, :tags,
                    SDO_UTIL.FROM_GEOJSON(:geometry)
                )
            """, rows)

            cursor.execute("""
                SELECT COUNT(*), COUNT(DISTINCT osm_key), COUNT(geom)
                FROM substation_sites
            """)
            counts = cursor.fetchone()
            if counts != (1309, 1309, 1309):
                raise RuntimeError(f"Reconciliation failed: {counts}")

            cursor.execute("""
                SELECT COUNT(*)
                FROM substation_sites s
                WHERE s.geom.SDO_SRID IS NULL
                   OR s.geom.SDO_SRID <> 4326
            """)
            if cursor.fetchone()[0]:
                raise RuntimeError("Unexpected geometry SRID")

            connection.commit()
            print("Committed: 1309 rows, 1309 unique keys, 1309 geometries.")
            print("All geometries have SRID 4326.")
        except Exception:
            connection.rollback()
            raise