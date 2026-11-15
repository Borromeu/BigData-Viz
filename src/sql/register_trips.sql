CREATE OR REPLACE VIEW trips AS
SELECT
    tpep_pickup_datetime AS pickup_at,
    CAST(trip_distance AS DOUBLE) AS distance_miles,
    COALESCE(CAST(PULocationID AS BIGINT), 0) AS pickup_zone
FROM {source_sql}
WHERE tpep_pickup_datetime IS NOT NULL
  AND tpep_pickup_datetime >= TIMESTAMP '{start_str}'
  AND tpep_pickup_datetime < TIMESTAMP '{end_str}'
  AND trip_distance IS NOT NULL
  AND isfinite(CAST(trip_distance AS DOUBLE))
  AND CAST(trip_distance AS DOUBLE) > 0