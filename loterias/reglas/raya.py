"""3 en raya: el capítulo 05 del libro "Máster Ka" (Conocimientos del Máster Ka).

Cada campo del libro empieza por un número y le siguen otros: "00-81-49-25".
Cuando sale el primero, se miran los que le siguen y su inverso (81 y 18, 49 y 94, 25 y 52),
y se juegan los que más salen. No se mira cada lotería por separado: se juntan todas y
sale una sola jugada con las parejas más fuertes.
"""

from __future__ import annotations

from collections import Counter

from ..db import Sorteo

CUANTOS = 3  # parejas número-inverso que se juegan

# Como está en el libro: el primer número de cada campo y los que le siguen
_CAMPOS = """
00-81-49-25  01-10-28-68  02-20-14-41  03-15-11     04-91        05-32-23     06-15-51
07-17-19     08-57-80     09-72        10-01-28-68  11-45        12-56-66     13-39-63
14-41-02-20  15-22-69     16-91        17-30-51     18-73-76     19-36
21-46-71     22-15-69     23-74        24-14-34     25-81-49-00  26-62-29     27-69
28-01-10     29-31        30-51-17     31-29        32-05-23     33-98-89     34-14-24
35-53-70     36-19        37-73-39-93  38-83-88     39-37-73-93  40-59-95-65
41-02-20-14  42-97-47     43-34-17     44-85-90     45-11-01     46-47-56-57  47-56-46-57
48-63        49-94-14     50-05        51-17-30     52-13-38     53-35-70     54-04
55-65        56-12-66     57-64-46     58-34        59-01        60-06-15
61-19        62-26        63-13-39     64-46-57     65-55        66-12-56     67-04-78
68-01-10-28  69-15-22     70-35        71-21-46     72-89        73-37        74-23
75-25        76-18-73     77-30        78-04-67     79-04        80-08-88
81-25        82-41        83-38-88     84-04-43     85-90-44     86-74-23     87-04-15
88-38-83     89-72        90-44-04     91-04        92-12        93-39-37-73  94-49-25
95-04        96-19        97-42        98-33        99-00
""".split()
# (el libro repite el 00 al final como "00-25-49-81": son los mismos números)

LIBRO: dict[str, list[str]] = {c[:2]: c.split("-")[1:] for c in _CAMPOS}


def _pareja(n: str) -> str:
    return min(n, n[::-1])


def jugar(historiales: dict[str, list[Sorteo]], veces: Counter) -> list[dict]:
    """Las CUANTOS parejas más fuertes, juntando todas las loterías de `historiales`.

    `historiales` son los sorteos anteriores de cada lotería (antiguo -> reciente) y `veces`
    cuántas veces salió cada número en todas ellas. Cada número del último sorteo de cada
    lotería que empieza un campo lo abre. De los que le siguen (con su inverso) va primero
    la pareja que más veces salió, en cualquier lotería, en el sorteo siguiente a uno de esa
    misma lotería donde salió ese primer número; en empate, la que más ha salido en total.
    """
    de: dict[str, list[str]] = {}  # pareja -> primeros números de campo que la traen
    for h in historiales.values():
        for p in h[-1].numeros if h else ():
            for n in LIBRO.get(p, []):
                de.setdefault(_pareja(n), [])
                if p not in de[_pareja(n)]:
                    de[_pareja(n)].append(p)

    despues: Counter = Counter()
    for h in historiales.values():
        for antes, ahora in zip(h, h[1:]):
            salieron = {_pareja(n) for n in ahora.numeros}
            for k, primeros in de.items():
                if k in salieron and any(p in antes.numeros for p in primeros):
                    despues[k] += 1

    def fuerza(k):
        return veces[k] + (veces[k[::-1]] if k != k[::-1] else 0)
    elegidas = sorted(de, key=lambda k: (-despues[k], -fuerza(k), k))[:CUANTOS]
    salida = []
    for k in elegidas:
        a, b = k, k[::-1]
        if veces[b] > veces[a]:
            a, b = b, a
        salida.append({"numero": a, "inverso": b, "despues": despues[k],
                       "veces": fuerza(k), "campos": sorted(de[k])})
    return salida
