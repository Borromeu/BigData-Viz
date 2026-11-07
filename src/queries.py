import duckdb

def get_trips_by_hour(conn: duckdb.DuckDBPyConnection, table_name: str, sample_rate: float = 1.0) -> duckdb.DuckDBPyRelation:
    """
    O1 / O3: Calculează numărul de curse pe ore (00-23).
    Dacă sample_rate < 1.0, aplică factorul de pondere (1 / sample_rate).
    """
    weight = 1.0 / sample_rate if sample_rate > 0 else 1.0
    
    query = f"""
        WITH hours AS (
            SELECT CAST(RANGE AS INTEGER) AS hour FROM range(0, 24)
        ),
        actual_trips AS (
            SELECT 
                EXTRACT(HOUR FROM tpep_pickup_datetime) AS hour,
                COUNT(*) * {weight} AS estimated_count
            FROM {table_name}
            WHERE tpep_pickup_datetime IS NOT NULL
            GROUP BY 1
        )
        SELECT 
            LPAD(CAST(h.hour AS VARCHAR), 2, '0') AS group_key,
            COALESCE(a.estimated_count, 0.0) AS value
        FROM hours h
        LEFT JOIN actual_trips a ON h.hour = a.hour
        ORDER BY h.hour;
    """
    return conn.sql(query)


def get_distance_distribution(conn: duckdb.DuckDBPyConnection, table_name: str, sample_rate: float = 1.0) -> duckdb.DuckDBPyRelation:
    """
    O2 / O3: Calculează distribuția distanțelor respectând intervalele din README:
    0: (0, 1)
    1: [1, 2)
    2: [2, 5)
    3: [5, 10)
    4: [10, +inf)
    Aplică factorul de pondere dacă sample_rate < 1.0.
    """
    weight = 1.0 / sample_rate if sample_rate > 0 else 1.0
    
    query = f"""
        WITH categorized AS (
            SELECT 
                CASE 
                    WHEN trip_distance > 0 AND trip_distance < 1 THEN 0
                    WHEN trip_distance >= 1 AND trip_distance < 2 THEN 1
                    WHEN trip_distance >= 2 AND trip_distance < 5 THEN 2
                    WHEN trip_distance >= 5 AND trip_distance < 10 THEN 3
                    WHEN trip_distance >= 10 THEN 4
                    ELSE -1
                END AS dist_bin,
                trip_distance
            FROM {table_name}
            WHERE trip_distance IS NOT NULL 
              AND trip_distance > 0 
              AND NOT (isnan(trip_distance) OR isinf(trip_distance))
        ),
        bins AS (
            SELECT CAST(RANGE AS INTEGER) AS dist_bin FROM range(0, 5)
        ),
        aggregated AS (
            SELECT 
                dist_bin,
                COUNT(*) * {weight} as estimated_count
            FROM categorized
            WHERE dist_bin >= 0
            GROUP BY 1
        )
        SELECT 
            CAST(b.dist_bin AS VARCHAR) AS group_key,
            COALESCE(a.estimated_count, 0.0) AS value
        FROM bins b
        LEFT JOIN aggregated a ON b.dist_bin = a.dist_bin
        ORDER BY b.dist_bin;
    """
    return conn.sql(query)


def get_top_zones(conn: duckdb.DuckDBPyConnection, table_name: str, limit: int = 10, sample_rate: float = 1.0) -> duckdb.DuckDBPyRelation:
    """
    Pregătire pentru final: Top zone de preluare cu ponderare opțională.
    """
    weight = 1.0 / sample_rate if sample_rate > 0 else 1.0
    
    query = f"""
        SELECT 
            COALESCE(CAST(PULocationID AS VARCHAR), 'Unknown') AS group_key,
            COUNT(*) * {weight} AS value
        FROM {table_name}
        WHERE PULocationID IS NOT NULL
        GROUP BY 1
        ORDER BY value DESC, group_key ASC
        LIMIT {limit};
    """
    return conn.sql(query)


if __name__ == "__main__":
    import json

    conn = duckdb.connect()

    # Încărcăm fixture-ul folosind calea corectă din tests/fixtures/
    conn.execute("""
        CREATE TABLE trips AS 
        SELECT * FROM read_csv_auto('tests/fixtures/trips.csv')
        WHERE fixture_id BETWEEN 1 AND 12;
    """)

    print("=== Rezultat O1: Curse pe ore (Exact) ===")
    res_hours = get_trips_by_hour(conn, "trips").fetchall()
    for row in res_hours:
        if row[1] > 0:
            print(row)

    print("\n=== Rezultat O2: Distribuția distanțelor (Exact, conform intervalelor din README) ===")
    res_dist = get_distance_distribution(conn, "trips").fetchall()
    for row in res_dist:
        print(row)