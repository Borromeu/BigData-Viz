COPY (
    SELECT *
    FROM {source_view}
    USING SAMPLE {sample_percent}% (bernoulli, {seed})
) TO (getvariable('sample_output_path')) (FORMAT PARQUET)
