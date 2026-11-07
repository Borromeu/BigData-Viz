import sys
import os
import duckdb
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))
from queries import get_trips_by_hour, get_distance_distribution

if __name__ == "__main__":
    conn = duckdb.connect()

    # Creăm un set de date artificial special pentru cazuri-limită (edge cases)
    # Conține: o valoare la limită (1.0), valori invalide (negativ, 0, inf, NaN) și ore izolate
    conn.execute("""
        CREATE TABLE edge_trips (
            fixture_id INTEGER,
            tpep_pickup_datetime TIMESTAMP,
            trip_distance DOUBLE,
            PULocationID INTEGER
        );
    """)

    # Inserăm date de test controlate
    conn.execute("""
        INSERT INTO edge_trips VALUES
        (1, '2025-01-15 00:30:00', 0.5, 1),  -- Ora 00, Bin 0 (0<d<1)
        (2, '2025-01-15 01:00:00', 1.0, 1),  -- Ora 01, Bin 1 (exact la limită: 1.0)
        (3, '2025-01-15 01:15:00', -1.0, 1), -- Distanță negativă (trebuie filtrată)
        (4, '2025-01-15 01:30:00', 'NaN', 1),-- Distanță NaN (trebuie filtrată)
        (5, '2025-01-15 23:45:00', 15.0, 2)  -- Ora 23, Bin 4 (>=10)
    """)

    print("=== Test O6: Verificare categorii absente (completate cu zero) și cazuri-limită ===")

    # 1. Verificăm că toate cele 24 de ore sunt prezente (chiar dacă majoritatea au 0 curse)
    hours_df = get_trips_by_hour(conn, "edge_trips", sample_rate=1.0).df()
    assert len(hours_df) == 24, "Trebuie să avem exact 24 de rânduri pentru ore (00-23)!"
    
    # Verificăm că ora 02 are valoarea 0.0 (categorie absentă completată cu zero)
    val_hour_2 = hours_df.loc[hours_df["group_key"] == "02", "value"].values[0]
    print(f"Valoarea pentru ora '02' (absentă în date): {val_hour_2} (Așteptat: 0.0)")
    assert val_hour_2 == 0.0

    # 2. Verificăm distribuția distanțelor pentru cazurile-limită
    dist_df = get_distance_distribution(conn, "edge_trips", sample_rate=1.0).df()
    print("\nDistribuția distanțelor pe datele de test limită:")
    print(dist_df)

    # Bin 1 trebuie să conțină valoarea 1.0 (exact la limită)
    val_bin_1 = dist_df.loc[dist_df["group_key"] == "1", "value"].values[0]
    print(f"Valoarea pentru Bin 1 (distanța 1.0): {val_bin_1} (Așteptat: 1.0)")
    assert val_bin_1 == 1.0

    print("\n🎉 Toate testele pentru O6 (cazuri-limită și categorii absente) au trecut cu succes!")