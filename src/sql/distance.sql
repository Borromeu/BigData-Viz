WITH bins AS (
    SELECT CAST(range AS INTEGER) AS dist_bin FROM range(0, 5)
),
categorized AS (
    SELECT CASE
        WHEN distance_miles > 0 AND distance_miles < 1 THEN 0
        WHEN distance_miles >= 1 AND distance_miles < 2 THEN 1
        WHEN distance_miles >= 2 AND distance_miles < 5 THEN 2
        WHEN distance_miles >= 5 AND distance_miles < 10 THEN 3
        WHEN distance_miles >= 10 THEN 4
        ELSE -1 END AS dist_bin
    FROM {table_name}
    WHERE {ELIGIBLE_FILTER}
),
aggregated AS (
    SELECT dist_bin, COUNT(*) AS trip_count
    FROM categorized WHERE dist_bin >= 0 GROUP BY 1
)
SELECT CAST(b.dist_bin AS VARCHAR) AS group_key,
       COALESCE(a.trip_count, 0)::BIGINT AS value
FROM bins b LEFT JOIN aggregated a USING (dist_bin)
ORDER BY b.dist_bin