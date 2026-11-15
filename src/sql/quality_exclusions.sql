SELECT
    COUNT(*) AS raw_rows,
    COUNT(*) FILTER (
        WHERE tpep_pickup_datetime IS NULL
    ) AS missing_timestamp,
    COUNT(*) FILTER (
        WHERE tpep_pickup_datetime IS NOT NULL
          AND (tpep_pickup_datetime < TIMESTAMP '{start_str}' OR tpep_pickup_datetime >= TIMESTAMP '{end_str}')
    ) AS out_of_period,
    COUNT(*) FILTER (
        WHERE tpep_pickup_datetime IS NOT NULL
          AND tpep_pickup_datetime >= TIMESTAMP '{start_str}'
          AND tpep_pickup_datetime < TIMESTAMP '{end_str}'
          AND (trip_distance IS NULL OR NOT isfinite(CAST(trip_distance AS DOUBLE)))
    ) AS invalid_distance,
    COUNT(*) FILTER (
        WHERE tpep_pickup_datetime IS NOT NULL
          AND tpep_pickup_datetime >= TIMESTAMP '{start_str}'
          AND tpep_pickup_datetime < TIMESTAMP '{end_str}'
          AND trip_distance IS NOT NULL
          AND isfinite(CAST(trip_distance AS DOUBLE))
          AND CAST(trip_distance AS DOUBLE) <= 0
    ) AS nonpositive_distance
FROM {source_sql};