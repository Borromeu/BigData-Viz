from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path


# Căile nu depind de directorul din care este pornit Python.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"
RESULTS_DIR = PROJECT_ROOT / "results"
RUNS_DIR = RESULTS_DIR / "runs"
QUALITY_DIR = RESULTS_DIR / "quality"
TEMP_DIR = PROJECT_ROOT / "data" / "tmp"

CONFIG_VERSION = "1"
FILTER_VERSION = "1"

# Setări propuse în ghid.
QUERY_THREADS = 2
SAMPLING_THREADS = 1
DUCKDB_MEMORY_LIMIT = "2GB"

# Coloanele originale TLC și numele comune utilizate în proiect.
COLUMN_MAPPING = (
    ("tpep_pickup_datetime", "pickup_at"),
    ("trip_distance", "distance_miles"),
    ("PULocationID", "pickup_zone"),
)

# Intervalele sunt aplicate după filtrarea distanțelor <= 0.
# Limita inferioară este inclusivă, cea superioară exclusivă.
DISTANCE_BINS = (
    (0, 0.0, 1.0, "(0, 1)"),
    (1, 1.0, 2.0, "[1, 2)"),
    (2, 2.0, 5.0, "[2, 5)"),
    (3, 5.0, 10.0, "[5, 10)"),
    (4, 10.0, float("inf"), "[10, +inf)"),
)

RESULT_COLUMNS = (
    "run_id",
    "dataset_id",
    "config_version",
    "question",
    "method",
    "sample_rate",
    "seed",
    "group_key",
    "value",
    "status",
)

RESULT_STATUSES = ("ok", "empty_sample", "not_applicable")


def validate_sample_rate(value: float) -> None:
    """Acceptă probabilități finite în intervalul (0, 1]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("sample_rate trebuie să fie un număr.")

    if not isfinite(value) or not 0 < value <= 1:
        raise ValueError("sample_rate trebuie să fie finit și în (0, 1].")


def validate_seed(value: int) -> None:
    """bool este respins explicit, chiar dacă în Python derivă din int."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("seed trebuie să fie un întreg.")

    if not 0 <= value <= 4_294_967_295:
        raise ValueError("seed trebuie să fie în intervalul uint32.")


@dataclass(frozen=True)
class DatasetConfig:
    dataset_id: str
    files: tuple[Path, ...]
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not self.files:
            raise ValueError("Datasetul trebuie să aibă cel puțin un fișier.")

        if any(not isinstance(path, Path) for path in self.files):
            raise ValueError("Fișierele trebuie reprezentate prin Path.")

        # Datasetul TLC este tratat cu timestampuri locale, fără fus orar.
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("Perioada trebuie să folosească datetime fără fus.")

        if self.start >= self.end:
            raise ValueError("start trebuie să fie anterior lui end.")


@dataclass(frozen=True)
class StageConfig:
    questions: tuple[str, ...]
    sample_rates: tuple[float, ...]
    seeds: tuple[int, ...]
    repeats: int

    def __post_init__(self) -> None:
        if not self.questions or any(
            question not in ("hours", "distance", "zones")
            for question in self.questions
        ):
            raise ValueError("Lista întrebărilor este goală sau invalidă.")

        if not self.sample_rates or not self.seeds:
            raise ValueError("Procentele și seedurile nu pot fi goale.")

        for rate in self.sample_rates:
            validate_sample_rate(rate)

        for seed in self.seeds:
            validate_seed(seed)

        if (
            isinstance(self.repeats, bool)
            or not isinstance(self.repeats, int)
            or self.repeats < 1
        ):
            raise ValueError("repeats trebuie să fie un întreg pozitiv.")

        for values in (self.questions, self.sample_rates, self.seeds):
            if len(values) != len(set(values)):
                raise ValueError("Configurația nu permite valori duplicate.")


def get_dataset(dataset_id: str) -> DatasetConfig:
    if dataset_id == "jan":
        months = ("01",)
        end = datetime(2025, 2, 1)
    elif dataset_id == "q1":
        months = ("01", "02", "03")
        end = datetime(2025, 4, 1)
    else:
        raise ValueError(f"Dataset necunoscut: {dataset_id!r}")

    files = tuple(
        RAW_DIR / f"yellow_tripdata_2025-{month}.parquet"
        for month in months
    )

    return DatasetConfig(
        dataset_id=dataset_id,
        files=files,
        start=datetime(2025, 1, 1),
        end=end,
    )


def get_stage(stage: str) -> StageConfig:
    if stage == "pilot":
        return StageConfig(
            questions=("hours", "distance"),
            sample_rates=(0.01, 0.10),
            seeds=(42,),
            repeats=3,
        )

    if stage == "final":
        return StageConfig(
            questions=("hours", "distance", "zones"),
            sample_rates=(0.01, 0.05, 0.10),
            seeds=(42, 43, 44),
            repeats=5,
        )

    raise ValueError(f"Etapă necunoscută: {stage!r}")


def create_output_directories() -> None:
    """Apelată explicit de comenzile care generează rezultate."""
    for directory in (
        SAMPLES_DIR,
        RUNS_DIR,
        QUALITY_DIR,
        TEMP_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)