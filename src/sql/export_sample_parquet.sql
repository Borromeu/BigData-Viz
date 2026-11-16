
COPY (
    SELECT *
    FROM __sampling_relation
) TO (getvariable('sample_output_path')) (FORMAT PARQUET)
