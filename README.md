# BigData-Viz

Proiect pentru compararea agregării și eșantionării în vizualizarea interactivă a datelor de mobilitate urbană.

Echipă: Adelin, Vlad, Octavian și Ștefan.

## 1. Tehnologii

- Python 3.13.17
- DuckDB pentru interogări SQL asupra fișierelor Parquet
- Plotly pentru grafice interactive
- Notebook-uri executate în VS Code
- Mediu virtual Python local: `.venv`

DuckDB rulează în procesul Python. Nu necesită instalarea unui server separat.

## 2. Cerințe preliminare

Instalați:

1. [Git](https://git-scm.com/downloads)
2. [Python 3.13.17](https://www.python.org/downloads/release/python-31317/)
3. [Visual Studio Code](https://code.visualstudio.com/)

În VS Code, instalați extensiile publicate de Microsoft:

- Python — `ms-python.python`
- Jupyter — `ms-toolsai.jupyter`

Instrucțiunile de mai jos acoperă:

- macOS pe Apple Silicon: M1/M2/M3/M4;
- Windows cu Python x64.

Pentru macOS Intel sau Windows ARM64 trebuie pregătit un lockfile separat.

### Verificare macOS

După instalarea Python, deschideți un terminal nou:

```bash
git --version
python3.13 --version
python3.13 -c "import platform; print(platform.machine())"
```

Rezultate așteptate pentru Python și arhitectură:

```text
Python 3.13.17
arm64
```

### Verificare Windows

Într-un terminal PowerShell nou:

```powershell
git --version
py -3.13 --version
py -3.13 -c "import struct; print(struct.calcsize('P') * 8)"
```

Rezultate așteptate pentru Python și numărul de biți:

```text
Python 3.13.17
64
```

Instalați varianta standard CPython. Nu selectați varianta experimentală free-threaded.

## 3. Deschiderea proiectului

Clonați repository-ul folosind URL-ul disponibil în GitHub, din butonul **Code**.

Dacă repository-ul există deja pe laptop, folosiți copia existentă.

În VS Code:

1. Selectați **File → Open Folder**.
2. Deschideți rădăcina repository-ului.
3. Selectați **Terminal → New Terminal**.

Toate comenzile următoare se execută din rădăcina repository-ului, unde se află `requirements.in`.

## 4. Fișierele și directoarele proiectului

| Cale | Conținut |
|---|---|
| `data/` | Dataseturi locale, excluse din Git |
| `notebooks/` | Notebook-uri pentru verificări și analize |
| `results/` | Grafice și măsurători generate, excluse din Git |
| `src/` | Funcții Python reutilizabile |
| `.venv/` | Mediul local al proiectului, exclus din Git |
| `.venv-tools/` | Unelte pentru lockfile și audit, excluse din Git |
| `requirements.in` | Dependențele directe comune |
| `requirements-macos-arm64-py313.lock` | Dependențele fixate pentru macOS Apple Silicon |
| `requirements-windows-x64-py313.lock` | Dependențele fixate pentru Windows x64 |

### `requirements.in`

Fișierul trebuie să conțină:

```text
duckdb==1.5.6
plotly==7.1.0
ipykernel==7.4.0
nbformat==5.11.1
```

Acestea sunt versiunile alese pentru proiect. Auditul se face asupra lockfile-ului complet, inclusiv dependențele indirecte.

### `.gitignore`

Adăugați regulile următoare, păstrând alte reguli relevante existente:

```gitignore
.venv/
.venv-tools/
__pycache__/
*.py[cod]
.ipynb_checkpoints/
.env
.DS_Store

data/*
!data/.gitkeep

results/*
!results/.gitkeep
```

Nu adăugați lockfile-urile în `.gitignore`.

## 5. Setup pe macOS Apple Silicon

### 5.1. Creați mediul virtual

```bash
python3.13 -m venv .venv
```

Verificați interpreterul:

```bash
.venv/bin/python --version
.venv/bin/python -c "import sys; print(sys.executable); print(sys.prefix != sys.base_prefix)"
.venv/bin/python -m pip --version
```

Versiunea Python trebuie să fie `3.13.17`, calea trebuie să indice `.venv`, iar ultima valoare booleană trebuie să fie `True`.

Comenzile folosesc explicit interpreterul din `.venv`, deci activarea mediului nu este obligatorie.

### 5.2. Verificați existența lockfile-ului

Repository-ul trebuie să conțină:

```text
requirements-macos-arm64-py313.lock
```

Dacă lipsește, urmați secțiunea **10. Pregătirea lockfile-urilor**, apoi reveniți aici.

Nu folosiți vechiul lockfile generat în containerul Linux.

### 5.3. Instalați dependențele

```bash
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-macos-arm64-py313.lock
.venv/bin/python -m pip check
```

Rezultatul așteptat pentru ultima comandă:

```text
No broken requirements found.
```

## 6. Setup pe Windows x64

Comenzile din această secțiune se execută în PowerShell.

### 6.1. Creați mediul virtual

```powershell
py -3.13 -m venv .venv
```

Verificați interpreterul:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); print(sys.prefix != sys.base_prefix)"
.\.venv\Scripts\python.exe -m pip --version
```

Versiunea Python trebuie să fie `3.13.17`, calea trebuie să indice `.venv`, iar ultima valoare booleană trebuie să fie `True`.

Folosim direct `python.exe` din `.venv`. Nu este necesară activarea mediului sau schimbarea politicii de execuție PowerShell.

### 6.2. Verificați existența lockfile-ului

Repository-ul trebuie să conțină:

```text
requirements-windows-x64-py313.lock
```

Dacă lipsește, urmați secțiunea **10. Pregătirea lockfile-urilor**, apoi reveniți aici.

Nu folosiți lockfile-ul pentru macOS sau vechiul lockfile Linux.

### 6.3. Instalați dependențele

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-windows-x64-py313.lock
.\.venv\Scripts\python.exe -m pip check
```

Rezultatul așteptat pentru ultima comandă:

```text
No broken requirements found.
```

## 7. Pregătirea directoarelor

Creați directoarele `data`, `notebooks`, `results` și `src` dacă lipsesc.

În directoarele goale, creați un fișier gol numit `.gitkeep`, pentru păstrarea lor în Git.

Pe macOS:

```bash
mkdir -p data notebooks results src
touch data/.gitkeep notebooks/.gitkeep results/.gitkeep src/.gitkeep
```

Pe Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path data, notebooks, results, src | Out-Null

foreach ($folder in @("data", "notebooks", "results", "src")) {
    $file = Join-Path $folder ".gitkeep"
    if (-not (Test-Path $file)) {
        New-Item -ItemType File -Path $file | Out-Null
    }
}
```

Datasetul poate fi adăugat ulterior în `data/`. Verificarea inițială folosește date demonstrative.

## 8. Configurarea VS Code

### 8.1. Selectați interpreterul

Deschideți Command Palette:

- macOS: `Cmd + Shift + P`;
- Windows: `Ctrl + Shift + P`.

Executați **Python: Select Interpreter** și selectați interpreterul din `.venv`.

Dacă nu apare automat, selectați manual:

- macOS: `.venv/bin/python`;
- Windows: `.venv\Scripts\python.exe`.

### 8.2. Selectați kernelul notebook-ului

1. Creați `notebooks/00_verificare.ipynb`.
2. Deschideți notebook-ul.
3. Apăsați **Select Kernel**, în dreapta sus.
4. Alegeți **Python Environments**.
5. Selectați mediul `.venv`.

Interpreterul editorului și kernelul notebook-ului trebuie verificate separat.

Nu este necesară înregistrarea globală a kernelului cu `ipykernel install --user`.

## 9. Verificarea setup-ului

Adăugați următoarele celule în `notebooks/00_verificare.ipynb`.

### Celula 1 — mediul Python și căile proiectului

```python
import sys
from pathlib import Path
from importlib.metadata import version

assert sys.version_info[:3] == (3, 13, 17), (
    f"Versiune Python neașteptată: {sys.version}"
)

assert sys.prefix != sys.base_prefix, (
    "Selectează kernelul din .venv."
)

print("Interpreter:", sys.executable)

for package in ("duckdb", "plotly", "ipykernel", "nbformat"):
    print(f"{package}: {version(package)}")

cwd = Path.cwd().resolve()

project_root = next(
    (
        folder
        for folder in (cwd, *cwd.parents)
        if (folder / "requirements.in").is_file()
        and (folder / "notebooks").is_dir()
    ),
    None,
)

assert project_root is not None, (
    "Deschide rădăcina repository-ului în VS Code."
)

data_dir = project_root / "data"
results_dir = project_root / "results"
results_dir.mkdir(exist_ok=True)

print("Proiect:", project_root)
```

### Celula 2 — interogare DuckDB

```python
import duckdb

with duckdb.connect(
    config={
        "memory_limit": "2GB",
        "threads": 2,
    }
) as con:
    rows = con.execute("""
        SELECT *
        FROM (VALUES
            ('A', 10),
            ('B', 20),
            ('C', 15)
        ) AS demo(categorie, valoare)
    """).fetchall()

assert rows == [("A", 10), ("B", 20), ("C", 15)]
print(rows)
```

Conexiunea se închide automat la ieșirea din blocul `with`.
Lista `rows` rămâne disponibilă în Python.

### Celula 3 — grafic interactiv și export

```python
import plotly.graph_objects as go

fig = go.Figure(
    go.Bar(
        x=[row[0] for row in rows],
        y=[row[1] for row in rows],
    )
)

fig.update_layout(
    title="Verificare setup — date demonstrative",
    xaxis_title="Categorie",
    yaxis_title="Valoare",
)

fig.show(renderer="plotly_mimetype")

output = results_dir / "verificare_setup.html"
fig.write_html(output, include_plotlyjs=True, full_html=True)

assert output.is_file()
print("Grafic exportat:", output)
```

Deschideți `results/verificare_setup.html` în browser.

Verificarea este reușită dacă:

- interpreterul aparține directorului `.venv`;
- toate importurile funcționează;
- interogarea DuckDB returnează cele trei rânduri;
- graficul apare în notebook;
- graficul exportat se deschide în browser și permite interacțiunea.

## 10. Pregătirea lockfile-urilor

Această secțiune se execută inițial de un membru pentru fiecare platformă.

După generare, audit și verificarea instalării, lockfile-urile se adaugă în Git prin PR. Ceilalți membri instalează direct din fișierul potrivit.

Lockfile-urile sunt specifice platformei și familiei Python 3.13. Ele pot conține diferențe în dependențele indirecte.

### 10.1. macOS Apple Silicon

Creați un mediu separat pentru unelte:

```bash
python3.13 -m venv .venv-tools
.venv-tools/bin/python -m pip install "pip-tools==7.6.2" "pip-audit==2.10.1"
.venv-tools/bin/python -m pip check
```

Generați lockfile-ul:

```bash
.venv-tools/bin/pip-compile --generate-hashes --output-file=requirements-macos-arm64-py313.lock requirements.in
```

Auditați dependențele proiectului:

```bash
.venv-tools/bin/pip-audit --require-hashes -r requirements-macos-arm64-py313.lock
```

Auditați și mediul uneltelor:

```bash
.venv-tools/bin/python -m pip_audit
```

### 10.2. Windows x64

Creați un mediu separat pentru unelte:

```powershell
py -3.13 -m venv .venv-tools
.\.venv-tools\Scripts\python.exe -m pip install "pip-tools==7.6.2" "pip-audit==2.10.1"
.\.venv-tools\Scripts\python.exe -m pip check
```

Generați lockfile-ul:

```powershell
.\.venv-tools\Scripts\pip-compile.exe --generate-hashes --output-file=requirements-windows-x64-py313.lock requirements.in
```

Auditați dependențele proiectului:

```powershell
.\.venv-tools\Scripts\pip-audit.exe --require-hashes -r requirements-windows-x64-py313.lock
```

Auditați și mediul uneltelor:

```powershell
.\.venv-tools\Scripts\python.exe -m pip_audit
```

### 10.3. Interpretarea auditului

Rezultatul urmărit este:

```text
No known vulnerabilities found
```

Dacă apar vulnerabilități, păstrați raportul și evaluați actualizarea pachetelor afectate înainte de distribuirea configurației.

Un audit fără constatări se referă la vulnerabilitățile cunoscute în baza de date consultată pentru pachetele analizate. Nu certifică securitatea întregului laptop sau a tuturor componentelor native și JavaScript.

Instalarea inițială a uneltelor fixează versiunile lor directe, dar nu folosește un lockfile cu hash-uri pentru toate dependențele acestora.

După pregătirea lockfile-ului, reveniți la secțiunea de instalare pentru sistemul vostru.

## 11. Lucrul zilnic

1. Actualizați branch-ul de lucru conform workflow-ului Git al echipei.
2. Deschideți repository-ul în VS Code.
3. Selectați kernelul `.venv`.
4. Rulați celulele notebook-ului în ordine.
5. Salvați notebook-ul și codul.
6. Trimiteți modificările pe un branch separat.
7. Deschideți PR către `master` și solicitați review.

Instalarea dependențelor se repetă când lockfile-ul se modifică.

Pentru rularea scripturilor din terminal:

macOS:

```bash
.venv/bin/python src/nume_script.py
```

Windows:

```powershell
.\.venv\Scripts\python.exe src\nume_script.py
```

Înlocuiți `nume_script.py` cu numele unui script existent.

## 12. Închiderea sesiunii

Dacă ați creat o conexiune explicită:

```python
con = duckdb.connect()
```

Închideți-o când terminați:

```python
con.close()
```

Conexiunile create cu `with duckdb.connect(...) as con:` se închid automat.

Salvați notebook-ul. Pentru oprirea kernelurilor, deschideți Command Palette și căutați:

```text
Jupyter: Shut Down All Kernels
```

Comanda afectează toate kernelurile Jupyter gestionate de instanța respectivă VS Code.

Închiderea tabului notebook-ului nu garantează oprirea kernelului.

La următoarea sesiune, rulați din nou celulele de la început. Fișierul `.ipynb` păstrează codul și outputurile salvate, nu variabilele Python sau baza DuckDB din memorie.

## 13. Reguli pentru date și securitate

- Păstrați dataseturile în `data/`.
- Păstrați exporturile și măsurătorile în `results/`.
- Nu urcați `.venv`, `.venv-tools`, credențiale sau fișiere `.env` în Git.
- Rulați numai codul notebook-urilor pe care le-ați verificat.
- `.venv` izolează bibliotecile Python, dar nu este un sandbox.
- Actualizați Python și dependențele prin modificări revizuite în PR.
- Procesați datele mari în DuckDB și transferați în Python rezultatele necesare graficelor.

## 14. Documentație oficială

- [Python — medii virtuale](https://docs.python.org/3.13/library/venv.html)
- [DuckDB 1.5 — Python API](https://duckdb.org/docs/1.5/clients/python/overview)
- [VS Code — kerneluri Jupyter](https://code.visualstudio.com/docs/datascience/jupyter-kernel-management)
- [Plotly — Python](https://plotly.com/python/)
- [pip-tools](https://github.com/pypa/pip-tools)
- [pip-audit](https://github.com/pypa/pip-audit)