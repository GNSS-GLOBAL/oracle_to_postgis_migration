SELECT validity, COUNT(*) AS feature_count
FROM (
    SELECT SDO_GEOM.VALIDATE_GEOMETRY_WITH_CONTEXT(
               s.geom, 0.005
           ) AS validity
    FROM substation_sites s
)
GROUP BY validity
ORDER BY validity;