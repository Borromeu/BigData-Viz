import duckdb
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from queries import get_distance_distribution
from plots import plot_distance_distribution

if __name__ == "__main__":
    conn = duckdb.connect()

    # 1. Date complete (exact)
    conn.execute("CREATE TABLE trips AS SELECT * FROM read_csv_auto('tests/fixtures/trips.csv') WHERE fixture_id BETWEEN 1 AND 12;")
    exact_dist = get_distance_distribution(conn, "trips", sample_rate=1.0).df()

    # 2. Eșantion manual
    conn.execute("CREATE TABLE sample_trips AS SELECT * FROM read_csv_auto('tests/fixtures/trips.csv') WHERE fixture_id IN (1, 3, 6, 9);")
    sample_rate = 1.0 / 3.0
    est_dist = get_distance_distribution(conn, "sample_trips", sample_rate=sample_rate).df()

    # Generăm graficul Plotly
    fig = plot_distance_distribution(exact_dist, est_dist, sample_rate=sample_rate)
    
    # Salvăm ca HTML pentru prezentare / demo
    output_path = "distance_distribution_demo.html"
    fig.write_html(output_path)
    
    print(f"Graficul a fost generat și salvat cu succes în: {output_path}")