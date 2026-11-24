# Verificare pe al doilea sistem de operare (Windows x64 - Vlad)

- **Sistem de operare**: Windows 10/11 x64
- **Arhitectură**: x86_64 / AMD64
- **Versiune Python**: 3.13.17 (în mediu `.venv`)
- **Motor SQL**: DuckDB 1.5
- **Lockfile utilizat**: `requirements-windows-x64-py313.lock`

## Rezultate Verificare și Reproducere (Task V6)

### 1. Mediu și Teste
- **Instalare din lockfile**: Validată. `pip check` nu a raportat conflicte de dependențe.
- **Suita de unittest-uri**: `python -m unittest discover -s tests` -> **PASSED (34/34 OK)**.

### 2. Verificare Date și Reconciliere (`pilot_01`)
- **Comandă CLI executată**: `python -m src.data --dataset all --check`
- **Rezultate reconciliere**:
  - **Dataset `jan` (Ianuarie 2025)**: 
    - Rânduri brute: `3.475.226`
    - Eligibile: `3.384.311`
    - Excluse: `91.015` (1 lipsă timestamp, 2 în afara perioadei, 3 distanță invalidă, 2 distanță nepozitivă)
  - **Dataset `q1` (Trimestrul 1 2025)**: 
    - Rânduri brute: `11.198.026`
    - Eligibile: `10.903.615`
    - Excluse: `294.411`
- **Comparație `pilot_01`**: Toate cele 29 de valori exacte (ore, intervale de distanță și categorii de excluderi) coincid 100% cu referința din proiect.

### 3. Notebook și Vizualizări Offline
- **Notebook `notebooks/00_verificare.ipynb`**: Rulat prin `Restart Kernel -> Run All` în VS Code. Toate celulele s-au executat fără erori.
- **HTML-uri offline**:
  - `results/verificare_setup.html` -> Deschis local în browser, redare corectă.
  - `results/distance_distribution_demo.html` -> Deschis local în browser, interactivitate Plotly funcțională offline.
