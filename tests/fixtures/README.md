# Fixture comun

Date sintetice pentru verificarea implementării.
Nu sunt curse reale și nu reprezintă rezultate experimentale.

## Fișiere

- trips.csv: 20 de rânduri cu numele coloanelor TLC.
- zones.csv: lookup fictiv pentru zone.
- expected.json: rezultate de referință calculate manual.

fixture_id este exclusiv pentru teste.

## Citirea datelor

Câmpurile CSV goale reprezintă valori lipsă.

La încărcare se folosesc tipuri explicite:
- fixture_id: întreg;
- tpep_pickup_datetime: timestamp;
- trip_distance: număr în virgulă mobilă;
- PULocationID: întreg, cu valori lipsă permise.

NaN și inf trebuie interpretate ca valori numerice nefinite.
Nu transformați automat toate coloanele în text și nu
înlocuiți valorile invalide înaintea testării filtrului.

## Populație eligibilă

Perioada: [2025-01-01, 2025-02-01).

Sunt eligibile numai rândurile cu:
- timestamp nenul și în perioada selectată;
- distanță finită și strict pozitivă.

Zona lipsă devine 0.
Zona 99 rămâne în populație, deși nu apare în lookup.

Rezultat: rândurile 1–12, exact 12 curse.

## Intervalele distanțelor

0: (0, 1)
1: [1, 2)
2: [2, 5)
3: [5, 10)
4: [10, +inf)

## Ordinea zonelor

Număr de curse descrescător.
La egalitate, ID numeric crescător.

Ordinea așteptată: 1, 2, 3, 0, 99.
Nu sortați ID-urile numeric reprezentate ca text alfabetic.

## Eșantion manual

Selectăm fixture_id 1, 3, 6, 9.
Probabilitatea de test este 1/3.
Estimarea fiecărei numărători este count / p.

Acest exemplu verifică estimatorul, nu generatorul aleator.

## Compararea rezultatelor

Numărătorile exacte trebuie să coincidă integral.
Pentru valorile estimate și metrici se folosește o toleranță
numerică, de exemplu 1e-9.

Nu modificați expected.json pentru a face un test să treacă.
O schimbare a fixture-ului se verifică independent și prin PR.