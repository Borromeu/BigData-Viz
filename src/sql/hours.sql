WITH hours AS (
    SELECT CAST(range AS INTEGER) AS hour FROM range(0, 24)
),
actual_trips AS (
    SELECT EXTRACT(HOUR FROM pickup_at) AS hour, COUNT(*) AS trip_count
    FROM {table_name}
    WHERE pickup_at IS NOT NULL
      AND distance_miles IS NOT NULL
      AND distance_miles > 0
      AND NOT (isnan(distance_miles) OR isinf(distance_miles))
    GROUP BY 1
)
SELECT LPAD(CAST(h.hour AS VARCHAR), 2, '0') AS group_key,
       COALESCE(a.trip_count, 0)::BIGINT AS value
FROM hours h LEFT JOIN actual_trips a ON h.hour = a.hour
ORDER BY h.hour