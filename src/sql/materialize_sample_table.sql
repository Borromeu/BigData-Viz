CREATE OR REPLACE TEMP TABLE sample_trips AS
SELECT *
FROM {source_view}
USING SAMPLE {sample_percent}% (bernoulli, {seed})
