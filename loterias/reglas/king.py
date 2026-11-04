"""Master King: los capítulos 05 y 07 del libro "Máster Ka".

Cada fila de esos capítulos empieza por un número y le siguen otros: "07-17-19".
En cada lotería se mira su último sorteo: cada número que salió y que empieza una fila
la abre, y se toman los que le siguen. De todos esos se juegan los CUANTOS que más
han salido en esa lotería.

    Ejemplo: en la Real salió 07  ->  capítulo 07 da 97, 17, 19, 70, 12 y 61
             se juegan los 4 de esos que más han salido en la Real
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from .raya import LIBRO as CAPITULO_05

CUANTOS = 4

# Capítulo 07 (Secuencias ejecutivas), fila por fila como está en el libro.
# (El libro dice "24-5-98": se toma como 24-05-98.)
_CAP7 = """
01-26-95  46-57-94  08-60-97  05-16-19-23-49  07-97  65-95  16-88  37-62
30-62-69  25-81  14-24-34  37-39  68-78  87-89  49-94  08-96
20-27-58  70-71-91  23-74-72-86-89  10-86  24-05-98  10-82  07-17-19  11-45
04-24-28-29-31  12-66  01-68  33-88  07-70  27-72  25-65-00  44-77
05-91  75-76  07-12-61  46-71  04-67-70  49-00  08-80-88  66-39-39  08-57-80  11-57-94
""".split()


def _juntar(*filas: tuple[str, list[str]]) -> dict[str, list[str]]:
    libro: dict[str, list[str]] = {}
    for primero, siguen in filas:
        lista = libro.setdefault(primero, [])
        lista += [n for n in siguen if n not in lista and n != primero]
    return libro


CAPITULO_07 = _juntar(*((f[:2], f.split("-")[1:]) for f in _CAP7))
LIBRO = _juntar(*CAPITULO_05.items(), *CAPITULO_07.items())


def jugar(salidos, veces: Counter, ultima: dict[str, date]) -> list[dict]:
    """Los CUANTOS números más salidos de las filas que abren los números `salidos`.

    En empate va primero el que traen más filas y luego el que salió más recientemente.
    """
    de: dict[str, list[str]] = {}  # número -> primeros de fila que lo traen
    for p in salidos:
        for n in LIBRO.get(p, []):
            if p not in de.setdefault(n, []):
                de[n].append(p)
    nunca = date.min
    elegidos = sorted(de, key=lambda n: (-veces[n], -len(de[n]), -ultima.get(n, nunca).toordinal(), n))
    return [{"numero": n, "veces": veces[n], "de": de[n]} for n in elegidos[:CUANTOS]]
