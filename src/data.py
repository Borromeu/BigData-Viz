import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence, Union

import duckdb
import pandas as pd

from src.config import (
    CONFIG_VERSION,
    FILTER_VERSION,
    PROJECT_ROOT,
    QUALITY_DIR,
    RAW_DIR,
    get_dataset,
)

SQL_DIR = Path(__file__).resolve().parent / "sql"
_REGISTER_TRIPS_SQL = (SQL_DIR / "register_trips.sql").read_text(encoding="utf-8")
_QUALITY_EXCLUSIONS_SQL = (SQL_DIR / "quality_exclusions.sql").read_text(encoding="utf-8")

MANIFEST_PATH = PROJECT_ROOT / "docs" / "data_manifest.json"

TLC_URLS = {
    "yellow_tripdata_2025-01.parquet": "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-01.parquet",
    "yellow_tripdata_2025-02.parquet": "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-02.parquet",
    "yellow_tripdata_2025-03.parquet": "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-03.parquet",
    "taxi_zone_lookup.csv": "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv",
}


def _get_source_sql(files: Sequence[Union[str, Path]]) -> str:
    """Returnează expresia SQL de citire DuckDB potrivită în funcție de extensie (.csv sau .parquet)."""
    files_list = [Path(f) for f in files]
    escaped = [f"'{f.as_posix().replace("'", "''")}'" for f in files_list]
    paths_arr = f"[{', '.join(escaped)}]"

    if all(f.suffix.lower() == ".csv" for f in files_list):
        return f"read_csv_auto({paths_arr})"
    if all(f.suffix.lower() == ".parquet" for f in files_list):
        return f"read_parquet({paths_arr})"

    return paths_arr


def compute_file_sha256(file_path: Path) -> tuple[int, str]:
    """Calculează dimensiunea și hash-ul SHA-256 în blocuri de 1MB (Taskul V1)."""
    if not file_path.exists():
        raise FileNotFoundError(f"Fișierul nu există: {file_path}")

    hasher = hashlib.sha256()
    size_bytes = 0

    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
            size_bytes += len(chunk)

    if size_bytes == 0:
        raise ValueError(f"Fișierul este gol (0 octeți): {file_path}")

    return size_bytes, hasher.hexdigest()


def generate_data_manifest(output_path: Path = MANIFEST_PATH) -> dict:
    """Generează/actualizează manifestul oficial (docs/data_manifest.json)."""
    manifest_entries = []

    for filename, url in TLC_URLS.items():
        file_path = RAW_DIR / filename
        if not file_path.exists():
            raise FileNotFoundError(f"Generare eșuată: fișierul brut lipseste: {file_path}")

        size_bytes, sha256_hash = compute_file_sha256(file_path)
        manifest_entries.append({
            "filename": filename,
            "relative_path": f"data/raw/{filename}",
            "url": url,
            "size_bytes": size_bytes,
            "sha256": sha256_hash,
        })

    manifest_data = {
        "generated_at": datetime.now().isoformat(),
        "files": manifest_entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    return manifest_data


def verify_data_manifest(manifest_path: Path = MANIFEST_PATH, files_to_check: Sequence[Path] | None = None) -> bool:
    """Verifică integritatea fișierelor curente față de manifestul existent fără a-l modifica."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifestul nu există: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    manifest_map = {entry["filename"]: entry for entry in manifest.get("files", [])}
    target_files = [RAW_DIR / fname for fname in TLC_URLS.keys()] if files_to_check is None else [Path(f) for f in files_to_check]

    for file_path in target_files:
        filename = file_path.name
        if filename not in manifest_map:
            raise ValueError(f"Integritate eșuată: fișierul {filename} nu este înregistrat în manifest.")
        entry = manifest_map[filename]
        if not file_path.exists():
            message = f"Integritate eșuată: fișierul nu există pe disc: {file_path}"
            if entry.get("url"):
                message += f"\nSursa de descărcare: {entry['url']}"
            raise FileNotFoundError(message)

        current_size, current_hash = compute_file_sha256(file_path)

        if current_size != entry["size_bytes"]:
            raise ValueError(f"Dimensiune necorespunzătoare pentru {filename}: așteptat {entry['size_bytes']}, obținut {current_size}")
        if current_hash != entry["sha256"]:
            raise ValueError(f"Amprentă SHA-256 necorespunzătoare pentru {filename}: așteptat {entry['sha256']}, obținut {current_hash}")

    return True


def validate_schema(con: duckdb.DuckDBPyConnection, files: Sequence[Path]) -> None:
    """Verifică existența celor 3 coloane necesare (Taskul V2)."""
    required_cols = {"tpep_pickup_datetime", "trip_distance", "PULocationID"}
    source_sql = _get_source_sql(files)

    try:
        describe_df = con.execute(f"DESCRIBE SELECT * FROM {source_sql}").df()
        present_cols = set(describe_df["column_name"].tolist())
    except Exception as exc:
        raise ValueError(f"Eroare la citirea schemei fișierelor {files}: {exc}") from exc

    missing = required_cols - present_cols
    if missing:
        raise ValueError(f"Fișierele {files} nu conțin coloanele necesare: {sorted(missing)}")


def register_trips(
    con: duckdb.DuckDBPyConnection,
    files: Union[Path, Sequence[Path]],
    start: datetime,
    end: datetime,
) -> None:
    """Creează în DuckDB vederea filtrată `trips` din șablonul SQL (Taskul V3)."""
    files_list = [Path(files)] if isinstance(files, (str, Path)) else [Path(f) for f in files]

    if not files_list:
        raise ValueError("Lista de fișiere nu poate fi goală.")
    if start >= end:
        raise ValueError("start trebuie să fie anterior lui end.")

    validate_schema(con, files_list)

    query = _REGISTER_TRIPS_SQL.format(
        source_sql=_get_source_sql(files_list),
        start_str=start.strftime("%Y-%m-%d %H:%M:%S"),
        end_str=end.strftime("%Y-%m-%d %H:%M:%S"),
    )
    con.execute(query)


def check_dataset_quality(con: duckdb.DuckDBPyConnection, dataset_id: str) -> dict:
    """Calculează excluderile disjuncte și reconcilierea totală (Taskurile V4/V9)."""
    ds = get_dataset(dataset_id)

    # Verifică manifestul înainte de profilare
    verify_data_manifest(MANIFEST_PATH, ds.files)

    source_sql = _get_source_sql(ds.files)
    start_str = ds.start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = ds.end.strftime("%Y-%m-%d %H:%M:%S")

    register_trips(con, ds.files, ds.start, ds.end)
    eligible_count = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]

    query = _QUALITY_EXCLUSIONS_SQL.format(
        source_sql=source_sql,
        start_str=start_str,
        end_str=end_str,
    )
    res = con.execute(query).fetchone()

    raw_count = res[0]
    missing_ts = res[1]
    out_of_period = res[2]
    invalid_dist = res[3]
    nonpositive_dist = res[4]
    excluded_total = missing_ts + out_of_period + invalid_dist + nonpositive_dist

    if raw_count != eligible_count + excluded_total:
        raise ValueError(
            f"Eroare reconciliere {dataset_id}: brute ({raw_count}) != eligibile ({eligible_count}) + excluse ({excluded_total})"
        )

    report = {
        "dataset_id": dataset_id,
        "config_version": CONFIG_VERSION,
        "filter_version": FILTER_VERSION,
        "period": f"[{start_str}, {end_str})",
        "units": "miles",
        "raw_rows": raw_count,
        "eligible_rows": eligible_count,
        "excluded_rows": excluded_total,
        "exclusions": {
            "missing_timestamp": missing_ts,
            "out_of_period": out_of_period,
            "invalid_distance": invalid_dist,
            "nonpositive_distance": nonpositive_dist,
        },
    }

    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    out_file = QUALITY_DIR / f"{dataset_id}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def load_zone_lookup(lookup_path: Path = RAW_DIR / "taxi_zone_lookup.csv") -> dict[int, str]:
    """Citește CSV-ul de zone și validează unicitatea LocationID (Taskul V5)."""
    if not lookup_path.exists():
        raise FileNotFoundError(f"Fișierul lookup de zone nu există: {lookup_path}")

    df = pd.read_csv(lookup_path)
    required = {"LocationID", "Borough", "Zone"}
    if not required.issubset(df.columns):
        raise ValueError(f"Fișierul lookup nu conține coloanele {required}")

    if df["LocationID"].isna().any():
        raise ValueError("LocationID conține valori nule în lookup.")

    df["clean_id"] = pd.to_numeric(df["LocationID"], errors="coerce")
    if df["clean_id"].isna().any() or (df["clean_id"] % 1 != 0).any():
        raise ValueError("LocationID conține valori neîntregi.")

    df["clean_id"] = df["clean_id"].astype(int)

    if df["clean_id"].duplicated().any():
        dups = df[df["clean_id"].duplicated()]["clean_id"].tolist()
        raise ValueError(f"LocationID conține valori duplicate în lookup: {dups}")

    return {
        int(row["clean_id"]): f"{row['Zone']} ({row['Borough']})"
        for _, row in df.iterrows()
    }


def format_zone_name(zone_id: int, lookup_map: dict[int, str]) -> str:
    """Etichetează o zonă agregată (Taskul V5)."""
    if zone_id == 0:
        return "Zonă lipsă"
    return lookup_map.get(zone_id, f"Zonă necunoscută ({zone_id})")


def main():
    parser = argparse.ArgumentParser(description="Modulul de verificare și filtrare a datelor Vlad (V1-V9).")
    parser.add_argument("--dataset", choices=["jan", "q1", "all"], default="jan", help="Datasetul de verificat")
    parser.add_argument("--check", action="store_true", help="Rulează profilarea și verificarea de calitate")
    parser.add_argument("--manifest", action="store_true", help="Generează manifestul SHA-256")
    args = parser.parse_args()

    if args.manifest:
        manifest = generate_data_manifest()
        print(f"[OK] Manifest generat în docs/data_manifest.json ({len(manifest['files'])} fișiere).")

    if args.check or not args.manifest:
        con = duckdb.connect()
        try:
            datasets = ["jan", "q1"] if args.dataset == "all" else [args.dataset]
            for ds_id in datasets:
                report = check_dataset_quality(con, ds_id)
                print(f"[OK] Verificare calitate pentru {ds_id}: {report['eligible_rows']} rânduri eligibile din {report['raw_rows']} brute.")
        finally:
            con.close()


if __name__ == "__main__":
    main()
