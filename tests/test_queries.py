import sys
import os
import duckdb
import json
import pandas as pd

# Adăugăm folderul src în Calea Python ca să găsească modulele
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from queries import get_trips_by_hour, get_distance_distribution
from metrics import calculate_hours_error, calculate_distance_total_variation

if __name__ == "__main__":
    conn = duckdb.connect()

    # 1. Încărcăm datele complete (populația eligibilă: fixture_id 1-12)
    # Atenție: Calea către CSV este relativă la directorul de unde rulezi comanda (rădăcina proiectului)
    conn.execute("""
        CREATE TABLE trips AS 
        SELECT * FROM read_csv_auto('tests/fixtures/trips.csv')
        WHERE fixture_id BETWEEN 1 AND 12;
    """)

    # Obținem datele exacte
    exact_hours = get_trips_by_hour(conn, "trips", sample_rate=1.0).df()
    exact_dist = get_distance_distribution(conn, "trips", sample_rate=1.0).df()

    # --- A. Test fidelitate pe date identice ---
    err_hours_self = calculate_hours_error(exact_hours, exact_hours)
    err_dist_self = calculate_distance_total_variation(exact_dist, exact_dist)
    
    print("=== Test O4: Fidelitate pe date identice ===")
    print(f"Eroare ore (identic): {err_hours_self} (Așteptat: 0.0)")
    print(f"Eroare distanțe (identic): {err_dist_self} (Așteptat: 0.0)")
    assert err_hours_self == 0.0 and err_dist_self == 0.0, "Eroare la testul de fidelitate!"

    # --- B. Test eșantion manual vs expected.json ---
    conn.execute("""
        CREATE TABLE sample_trips AS 
        SELECT * FROM read_csv_auto('tests/fixtures/trips.csv')
        WHERE fixture_id IN (1, 3, 6, 9);
    """)

    sample_rate = 1.0 / 3.0
    est_hours = get_trips_by_hour(conn, "sample_trips", sample_rate=sample_rate).df()
    est_dist = get_distance_distribution(conn, "sample_trips", sample_rate=sample_rate).df()

    calc_hours_err = calculate_hours_error(exact_hours, est_hours)
    calc_dist_tv = calculate_distance_total_variation(exact_dist, est_dist)

    with open('tests/fixtures/expected.json', 'r') as f:
        expected = json.load(f)

    exp_hours_err = expected['manual_sample']['hours_normalized_absolute_error']
    exp_dist_tv = expected['manual_sample']['distance_total_variation']

    print("\n=== Test O4: Eșantion manual vs Expected.json ===")
    print(f"Eroare oră calculată: {calc_hours_err} | Așteptat: {exp_hours_err}")
    print(f"Distanță TV calculată: {calc_dist_tv} | Așteptat: {exp_dist_tv}")

    assert abs(calc_hours_err - exp_hours_err) < 1e-9, "Eroarea la ore nu corespunde cu expected.json!"
    assert abs(calc_dist_tv - exp_dist_tv) < 1e-9, "Distanța TV nu corespunde cu expected.json!"
    
    print("\n🎉 Toate testele din O4 au trecut cu succes și se potrivesc perfect cu expected.json!")