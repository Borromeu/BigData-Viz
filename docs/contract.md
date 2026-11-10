# Contractul comun al proiectului

Configurație: versiunea 1.
Filtrare: versiunea 1.

## Dataseturi și etape

- jan: ianuarie 2025; [2025-01-01, 2025-02-01).
- q1: ianuarie–martie 2025; [2025-01-01, 2025-04-01).
- pilot: hours și distance; 1%, 10%; seed 42; 3 repetări.
- final: hours, distance, zones; 1%, 5%, 10%;
  seeduri 42, 43, 44; 5 repetări.

Configurația se citește din src/config.py.
Nu duplicăm aceste valori în notebook sau în module.

## Populația comună

Vederea DuckDB trips conține:

- pickup_at: timestampul preluării;
- distance_miles: distanța în mile;
- pickup_zone: ID-ul zonei de preluare.

Păstrăm numai timestampuri nenule din intervalul [start, end)
și distanțe finite, strict pozitive.

Zona lipsă devine 0. ID-urile necunoscute rămân în populație.
Nu eliminăm automat duplicate sau distanțe mari finite.
Nu introducem conversie UTC implicită.

Exactul și eșantioanele folosesc aceeași populație filtrată.

## Interfețele de implementat

- Vlad:
  register_trips(con, files, start, end)

- Octavian:
  query_counts(con, question, source)
  evaluate(exact_rows, estimated_rows, question)

- Ștefan:
  build_sample(con, p, seed, output)
  estimate_counts(counts, p)

- Autorii figurilor:
  build_hours_figure(rows)
  build_distance_figure(rows)
  build_zones_figure(rows)

query_counts returnează o listă de perechi (group_key, count).
Sursele SQL sunt validate printr-o listă internă permisă.

Funcțiile de vizualizare primesc numai rezultate agregate.
Nu încarcă datele brute și nu execută SQL.

Codul care creează conexiunea DuckDB răspunde de închiderea ei.

## Rezultate

results.csv folosește coloanele RESULT_COLUMNS din config.py.

- method: exact sau sample.
- Exact: sample_rate=1; seed gol.
- Sample: probabilitatea p și seedul efectiv.
- Estimarea numărătorilor: count / p, aplicată o singură dată.
- group_key: text; ore 00–23, intervale 0–4, ID-uri de zone.
- Categoriile absente primesc zero pentru numărători.
- CSV folosește punct zecimal.
- status: ok, empty_sample sau not_applicable.

Un eșantion gol nu are o distribuție de proporții definită.
Nu îl reprezentăm ca distribuție uniformă sau eroare zero.

Fiecare rulare înregistrează CONFIG_VERSION și FILTER_VERSION
în manifestul propriu.

## Modificarea contractului

Orice schimbare se face prin PR cu aprobarea altui membru.
Schimbarea filtrelor invalidează eșantioanele și rezultatele
obținute cu filtrul anterior.

## Organizarea și executarea SQL-ului

Interogările SQL ale aplicației se păstrează în fișiere `.sql`
din `src/sql/`, versionate împreună cu restul codului.

Python răspunde de:
- validarea parametrilor și a surselor;
- încărcarea fișierelor SQL;
- executarea interogărilor;
- prelucrarea și exportarea rezultatelor.

### Structură

src/
├── queries.py
├── data.py
├── sampling.py
└── sql/
    ├── hours.sql
    ├── distance.sql
    └── ...

Fiecare fișier SQL are un scop clar. Agregările comune sunt
reutilizate pentru exact și sample, fără duplicarea SQL-ului.

### Reguli

1. Interogările aplicației nu sunt definite în stringuri SQL
   în fișierele Python sau în notebookuri.

2. Fișierele SQL se selectează printr-o mapare internă.
   Nu acceptăm căi arbitrare furnizate de utilizator.

3. Valorile dinamice se transmit prin parametri SQL.
   Nu se introduc prin f-string, concatenare sau `.format()`.

4. Identificatorii dinamici, precum numele surselor, provin
   exclusiv din mapări interne cu opțiuni permise.
   Opțiunile necunoscute produc ValueError înainte de execuție.

5. Căile către fișierele SQL sunt construite pornind de la
   locația modulului, fără dependență de directorul curent.

6. Pentru benchmark, încărcarea șabloanelor SQL se face înainte
   de pornirea cronometrului. Măsurarea include execuția
   interogării și obținerea rezultatului agregat.

7. Schimbarea unui fișier SQL necesită verificarea testelor
   funcționale afectate și review de la alt membru.

### Excepții limitate

Instrucțiunile scurte pentru configurarea conexiunii și SQL-ul
folosit exclusiv la pregătirea datelor sintetice în teste pot
rămâne în Python.

Excepțiile nu permit duplicarea interogărilor aplicației în teste.

### Securitate

Separarea în fișiere `.sql` este o regulă de organizare.
Protecția împotriva SQL injection este asigurată prin
parametrizarea valorilor și controlul identificatorilor.