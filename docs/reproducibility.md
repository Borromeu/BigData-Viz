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
USING SAMPLE {sample_percent}% (bernoulli, {seed})
```

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
Populația filtrată eligibilă conține $N \approx 3.475.000$ rânduri:
* Pentru **$p = 0.01$ (1%)**:
  * $\mathbb{E}[n] \approx 34.750$ rânduri, $\sigma \approx 185$ rânduri.
  * Realizarea obținută cu seed-ul 42: **33.709 rânduri**.
* Pentru **$p = 0.10$ (10%)**:
  * $\mathbb{E}[n] \approx 347.500$ rânduri, $\sigma \approx 559$ rânduri.
  * Realizarea obținută cu seed-ul 42: **338.916 rânduri**.

Abaterile observate sunt perfect normale din punct de vedere statistic și reflectă natura metodei Bernoulli, fără a constitui o eroare de implementare.

---

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
