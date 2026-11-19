# A6 — Reproducerea pilotului NYC Yellow Taxi

Porniți de la commitul din PR și executați comenzile din rădăcina `BigData-Viz`.
Folosiți CPython 3.13.17 și lockfile-ul pentru macOS Apple Silicon sau Windows
x64. Configurarea VS Code și alegerea kernelului sunt descrise în
[README](../README.md).

## 1. Instalarea și verificarea mediului

macOS Apple Silicon

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-macos-arm64-py313.lock
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -q
```

Windows x64, în PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-windows-x64-py313.lock
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Opriți-vă la prima eroare. Testele folosesc fixture-uri și se pot rula înainte
de descărcarea datelor TLC.

## 2. Reproducerea pe date reale

Pentru pilot descărcați `yellow_tripdata_2025-01.parquet` în `data/raw/` dacă
fișierul lipsește. Verificarea de calitate compară mărimea și SHA-256 cu
[manifestul datelor](data_manifest.json), apoi calculează populația eligibilă.
Folosiți URL-ul din manifest dacă trebuie să descărcați din nou fișierul.

macOS

```bash
mkdir -p data/raw
jan_file=data/raw/yellow_tripdata_2025-01.parquet
if [ ! -f "$jan_file" ]; then
  curl -fL --retry 2 'https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-01.parquet' -o "$jan_file.part" &&
  mv "$jan_file.part" "$jan_file"
fi
```

Windows PowerShell

```powershell
New-Item -ItemType Directory -Force data/raw | Out-Null
$janFile = 'data/raw/yellow_tripdata_2025-01.parquet'
if (-not (Test-Path $janFile)) {
    curl.exe -fL --retry 2 'https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-01.parquet' -o "$janFile.part"
    if ($LASTEXITCODE -ne 0) { throw 'Descărcarea fișierului TLC a eșuat.' }
    Move-Item "$janFile.part" $janFile
}
```

Alegeți un ID nou pentru fiecare benchmark. Comenzile folosesc `pilot_01` ca
exemplu. Folosiți același ID pentru benchmark, export și notebook.

macOS

```bash
.venv/bin/python -m src.data --dataset jan --check &&
.venv/bin/python -m src.sampling --stage pilot --dataset jan &&
.venv/bin/python -m src.benchmark --stage pilot --dataset jan --run-id pilot_01 &&
.venv/bin/python -m src.render --run-id pilot_01
```

Windows PowerShell

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -m src.data --dataset jan --check
if ($LASTEXITCODE -ne 0) { throw 'Verificarea datelor a eșuat.' }
& $python -m src.sampling --stage pilot --dataset jan
if ($LASTEXITCODE -ne 0) { throw 'Eșantionarea a eșuat.' }
& $python -m src.benchmark --stage pilot --dataset jan --run-id pilot_01
if ($LASTEXITCODE -ne 0) { throw 'Benchmarkul a eșuat.' }
& $python -m src.render --run-id pilot_01
```

Descărcarea depinde de conexiune. Verificarea integrității, eșantionarea și
benchmarkul citesc date locale și pot dura diferit pe fiecare laptop. Spațiul
observat pentru pilot a fost de aproximativ 59 MB pentru Parquet-ul brut, 3,3 MB
pentru eșantioane și 9,7 MB pentru cele două HTML-uri, fără `.venv`.

## 3. Verificarea și demonstrația

- Raportul `results/quality/jan.json` trebuie să arate **3.384.311 eligibile din
  3.475.226 rânduri brute** și **90.915 excluderi**.
- În `results/runs/pilot_01/`, manifestul are `status=complete`, `data_kind=real`
  și indică **18 măsurători, 87 de rânduri de rezultate și 4 erori**. Comparați
  rândurile `method=exact` după `(question, group_key)` cu rularea de referință.
  Cele 24 de ore și cele cinci intervale trebuie să coincidă pe ambele sisteme.
- Deschideți `notebooks/demo.ipynb` în VS Code, selectați kernelul `.venv` și
  executați **Restart Kernel → Run All**. Verificați cele două grafice,
  opțiunile de eșantionare și tabelele cu timpi, erori și costuri de generare.
- Deschideți `hours.html` și `distance.html` fără internet. Pentru o rulare
  completă, `src.render` regenerează HTML-urile din `results.csv` și
  `run_manifest.json`. Notebookul mai citește `timings.csv` și `errors.csv`.

Păstrați `pilot_01` ca referință pentru prezentare și stocați separat rularea
de verificare. Consemnați în [`platform_checks.md`](platform_checks.md) sistemul,
versiunile, commitul, totalul eligibil, comparația agregărilor și rezultatul
demo-ului offline. Pentru eșantioane urmați [protocolul S6](reproducibility.md).

## Verificare rapidă pe fixture

Comenzile de mai jos rulează fluxul cu datele de test deja din Git. Activați
`.venv` sau folosiți calea explicită spre interpreterul platformei. Schimbați
`RUN_ID` în notebook la `fixture_demo_01`.

```bash
python -m src.benchmark --fixture --run-id fixture_demo_01
python -m src.render --run-id fixture_demo_01
```

Datele brute, eșantioanele, mediul `.venv` și rulările generate rămân locale.
PR-ul include codul, lockfile-urile, notebookul sursă și instrucțiunile.
