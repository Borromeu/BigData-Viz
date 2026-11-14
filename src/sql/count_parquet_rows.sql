SELECT COUNT(*) AS row_count
FROM read_parquet(getvariable('sample_parquet_path'))
