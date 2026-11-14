SELECT *
FROM {source_view}
USING SAMPLE {sample_percent}% (bernoulli, {seed})
