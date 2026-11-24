# Reproductibilitatea eșantionării și limitele metodei

**Responsabil**: Ștefan (Taskul S6)  
**Proiect**: Vizualizarea interactivă a datelor de mobilitate urbană  
**Versiune**: 1.0 (Etapa Pilot)  

---

## 1. Protocolul de eșantionare Bernoulli în DuckDB

Pentru eșantionarea curselor de taxi se utilizează metoda **Bernoulli** cu seed explicit și execuție strict controlată pe un singur fir de execuție:

```sql
SELECT *
FROM trips
WHERE random() < getvariable('sampling_probability')
```
Implementarea folosește DuckDB 1.5.6 și realizează eșantionarea Bernoulli prin evaluarea condiției random() < p pentru fiecare rând. Probabilitatea p este transmisă printr-o variabilă DuckDB, iar generatorul aleator este inițializat înaintea fiecărei eșantionări prin setseed(). Seed-ul întreg este normalizat folosind formula seed / 4294967295.0. Pentru reproductibilitate, eșantionarea se execută cu threads = 1.

### De ce este obligatoriu `threads = 1`?
Documentația oficială DuckDB precizează explicit:
> *„A fixed random seed does not guarantee deterministic results when queries are executed on multiple threads.”*

Când DuckDB rulează cu mai multe thread-uri, scanarea tabelelor și partiționarea datelor între nuclee depind de planificatorul sistemului de operare. Aceasta duce la asignarea neuniformă a blocurilor de date către generatoarele pseudo-aleatoare, alterând ordinea și componența finală a rândurilor selectate, chiar dacă seed-ul este identic.

Prin urmare, biblioteca noastră implementează următorul mecanism în `src/sampling_core/engine.py` și `artifacts.py`:
1. Salvează setarea curentă a conexiunii (`previous_threads = get_threads(con)`).
2. Forțează `SET threads = 1` pe durata scanării și scrierii eșantionului.
3. Într-un bloc `finally`, restaurează setarea inițială (`previous_threads`), asigurând că interogările ulterioare de benchmark nu sunt încetinite artificial.

---

## 2. Proprietățile eșantionării și variația numărului de rânduri

### $p$ este o probabilitate de includere, nu o cotă fixă
În eșantionarea Bernoulli, fiecare rând eligibil din populația `trips` este inclus independent cu probabilitatea $p$. Dimensiunea finală $n$ a eșantionului este o variabilă aleatoare binomială:

$$n \sim \text{Binomial}(N, p)$$

* Valoarea așteptată: $\mathbb{E}[n] = N \cdot p$
* Varianța: $\text{Var}(n) = N \cdot p \cdot (1 - p)$
* Deviația standard: $\sigma = \sqrt{N \cdot p \cdot (1 - p)}$


### Exemplu concret pe datasetul NYC Yellow Taxi (ianuarie 2025):

Populația analizată este cea filtrată conform regulilor comune
din `src.data.register_trips()`, nu totalul rândurilor brute
din fișierul Parquet.

- Rânduri brute: **3.475.226**
- Rânduri eligibile: **3.384.311**
- Populația utilizată pentru sampling: **N = 3.384.311**

Pentru eșantionarea Bernoulli, numărul de rânduri selectate
urmează o distribuție binomială:

- E[n] = N × p
- Var(n) = N × p × (1 - p)
- σ = √(N × p × (1 - p))

**Pentru p = 0.01 (1%):**

- Valoarea așteptată: **33.843,11 rânduri**
- Deviația standard: **aproximativ 183,04 rânduri**
- Rezultatul observat, seed 42: **33.686 rânduri**
- Timpul de generare: **0,315 s**

**Pentru p = 0.10 (10%):**

- Valoarea așteptată: **338.431,10 rânduri**
- Deviația standard: **aproximativ 551,89 rânduri**
- Rezultatul observat, seed 42: **338.514 rânduri**
- Timpul de generare: **0,335 s**

### Interpretarea rezultatelor

Numărul efectiv de rânduri diferă de valoarea așteptată,
deoarece eșantionarea Bernoulli este probabilistică.

Ambele rezultate observate se află la mai puțin de o deviație
standard față de valoarea așteptată.

Testarea s-a realizat cu Python 3.13.2 și DuckDB 1.5.6,
folosind un singur fir de execuție și metoda
`random()` împreună cu `setseed()`.

Eșantioanele au fost generate în fișierele:

- `jan_rate-0.01_seed-42.parquet`
- `jan_rate-0.1_seed-42.parquet`

Manifestele JSON aferente au confirmat reutilizarea ambelor
eșantioane fără regenerare, păstrând timpii inițiali de
construire.

Reproductibilitatea presupune aceeași populație de intrare,
aceleași setări și aceeași versiune DuckDB. Rezultatele nu
sunt garantate identice între versiuni sau implementări
diferite ale eșantionării.


## 3. Comportamentul categoriilor rare și eșantioanelor goale

### Riscul pierderii grupurilor slab populate
Pentru categorii cu puține înregistrări (de exemplu, ore de noapte cu trafic redus sau zone de preluare periferice cu volum $N_k$ mic):
* Probabilitatea ca niciun rând din grupa $k$ să nu fie selectat este:

$$P(\text{categorie absentă}) = (1 - p)^{N_k}$$

Pentru o zonă cu $N_k = 50$ curse și o rată de $1\%$:
$$P(\text{absentă}) = (1 - 0.01)^{50} \approx 60.5\%$$

### Tratarea în proiect:
1. **Completare cu zero (`zero-fill`)**: Categoriile absente din eșantion sunt completate cu valoarea `0.0` la numărători, conform cerințelor din `queries.py` și `estimation.py`.
2. **Statut explicit `empty_sample`**: Dacă întregul eșantion nu conține date pentru o interogare, statusul devine `empty_sample`. Nu se inventează proporții uniforme sau erori zero.
3. **Păstrarea seed-ului fix**: Nu schimbăm seed-ul doar pentru că un anumit rezultat arată mai favorabil vizual; integritatea științifică impune raportarea variației naturale.

---

## 4. Politica de identificare, cache și reutilizare

Fiecare eșantion generat este însoțit de un fișier manifest JSON (`<nume>.manifest.json`).

### Criterii de reutilizare (`check_sample_reuse`):
Un eșantion este reutilizat (`reused = True`) doar dacă toate elementele următoare coincid exact:
1. **Hash-ul surselor**: SHA-256 al fiecărui fișier Parquet brut de intrare.
2. **Versiunea filtrelor**: `FILTER_VERSION` (modificarea regulilor invalidează automat cache-ul).
3. **Versiunea configurației**: `CONFIG_VERSION`.
4. **Parametrii de sampling**: $p$ (probabilitatea) și seed-ul întreg.
5. **Configurația DuckDB**: `sampling_threads = 1` și `memory_limit` identic.
6. **Integritatea eșantionului**: SHA-256 al fișierului Parquet generat corespunde valorii înregistrate în manifest.

Dacă oricare dintre aceste condiții este încălcată, reutilizarea este refuzată. Pentru a forța regenerarea, utilizatorul specifică flag-ul `--overwrite`.

---

## 5. Reproductibilitatea pe sisteme diferite (Cross-Platform)

1. **În același mediu controlat** (aceeași versiune DuckDB, aceleași fișiere de intrare, `threads = 1`, același seed):
   * Generarea este deterministă și reproduce identic multisetul de rânduri.
2. **Între versiuni diferite de DuckDB sau arhitecturi diferite** (ex. macOS ARM64 vs. Windows x64):
   * Implementarea internă a PRNG (Pseudo-Random Number Generator) din DuckDB poate varia între versiuni majore ale motorului SQL.
   * Pentru evaluarea comparativă de benchmark (A8/A9):
     - **Regulă comună**: Toate măsurătorile comparative principale se execută pe un singur laptop, folosind eșantioanele salvate local.
     - Dacă se dorește transferul pe un al doilea sistem, se copiază direct fișierele `.parquet` și `.manifest.json`, verificându-se hash-ul SHA-256.

---

## 6. Verificarea S6 pe Windows — 24 noiembrie 2026

### Mediul de testare

- Sistem: Windows x64
- Python: 3.13.2
- DuckDB: 1.5.6
- Commit de bază: `5da65b6`
- Dataset: NYC Yellow Taxi, ianuarie 2025
- Populație eligibilă: 3.384.311 rânduri
- Metodă: Bernoulli (`random()` + `setseed()`)
- Threads: 1
- Seed: 42

Dependențele au fost instalate folosind
`requirements-windows-x64-py313.lock`.
Verificarea `pip check` a trecut, iar suita completă
de teste a raportat 82/82 teste trecute.

Versiunea Python utilizată este 3.13.2, diferită de
versiunea 3.13.17 recomandată în documentația proiectului.

### Generarea independentă a eșantioanelor

Au fost efectuate două generări separate, folosind aceeași
populație, aceleași probabilități și același seed.

| Rată | Rânduri A | Rânduri B | Timp A | Timp B |
|---|---:|---:|---:|---:|
| 1% | 33.686 | 33.686 | 0,316 s | 0,390 s |
| 10% | 338.514 | 338.514 | 0,338 s | 0,385 s |

Directoarele utilizate:

- `data/samples/s6_run_a/`
- `data/samples/s6_run_b/`

### Compararea conținutului

Comparația a fost realizată în DuckDB prin `EXCEPT ALL`
în ambele direcții, pentru a păstra multiplicitatea
rândurilor duplicate.

| Rată | A minus B | B minus A | Conținut identic |
|---|---:|---:|---|
| 1% | 0 | 0 | Da |
| 10% | 0 | 0 | Da |

### Concluzie

Reproductibilitatea a fost confirmată pentru ambele rate,
în mediul Windows testat. Cele două generări independente
au produs același multiset de rânduri pentru fiecare
probabilitate și seed.

Timpii de construire diferă între execuții, dar această
variație nu afectează conținutul eșantioanelor.

Verificarea demonstrează reproductibilitatea în mediul
testat, nu identitatea rezultatelor între sisteme de operare,
arhitecturi sau versiuni diferite de DuckDB.
