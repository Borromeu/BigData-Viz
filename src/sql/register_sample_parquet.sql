CREATE OR REPLACE TEMP VIEW sample_trips AS
SELECT *
FROM read_parquet(getvariable('sample_parquet_path'))
