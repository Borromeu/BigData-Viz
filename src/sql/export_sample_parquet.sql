
COPY (
    SELECT *
    FROM trips
    WHERE random() < getvariable('sampling_probability')
) TO (getvariable('sample_output_path')) (FORMAT PARQUET)
