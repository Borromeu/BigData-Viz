CREATE OR REPLACE TEMP VIEW trips AS
SELECT
    CAST(tpep_pickup_datetime AS TIMESTAMP) AS pickup_at,
    CAST(trip_distance AS DOUBLE) AS distance_miles,
    COALESCE(CAST(PULocationID AS INTEGER), 0) AS pickup_zone
FROM read_parquet({parquet_vars})
WHERE tpep_pickup_datetime IS NOT NULL
  AND CAST(tpep_pickup_datetime AS TIMESTAMP) >= CAST(getvariable('period_start') AS TIMESTAMP)
  AND CAST(tpep_pickup_datetime AS TIMESTAMP) < CAST(getvariable('period_end') AS TIMESTAMP)
  AND trip_distance IS NOT NULL
  AND NOT (isnan(CAST(trip_distance AS DOUBLE)) OR isinf(CAST(trip_distance AS DOUBLE)))
  AND CAST(trip_distance AS DOUBLE) > 0
