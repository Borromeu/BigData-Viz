SELECT
    COUNT(*) AS row_count,
    COUNT(*) FILTER (WHERE
        pickup_at IS NULL
        OR pickup_at < CAST(getvariable('benchmark_start') AS TIMESTAMP)
        OR pickup_at >= CAST(getvariable('benchmark_end') AS TIMESTAMP)
        OR distance_miles IS NULL
        OR NOT isfinite(distance_miles)
        OR distance_miles <= 0
        OR pickup_zone IS NULL
    ) AS invalid_rows
FROM sample_trips;