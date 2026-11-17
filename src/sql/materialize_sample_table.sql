
CREATE OR REPLACE TEMP TABLE sample_trips AS
SELECT *
FROM trips
WHERE random() < getvariable('sampling_probability')
