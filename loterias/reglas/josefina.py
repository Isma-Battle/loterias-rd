"""Josefina: la "Guía Josefina loterías RD".

Cada número "jala" otros que salen detrás (su secuencia): "salió el 30 -> 85, 15, 70".
Cómo se juega, según la guía y el video de la autora:

  1. Para jugar una lotería hoy se mira lo que salió AYER en las loterías cuya secuencia
     sale en ella (página "Números indicados por loterías"; la primera siempre es ella misma).
  2. Se buscan esos números en la guía y se juegan los que jalan, protegidos con la V
     (fuerte el número derecho y algo al revés).
  3. La secuencia sale más al 2.º y 3.er día: si no salió hoy, se juega mañana otra vez
     y ahí se cierra.

Como de varias loterías salen muchos números, se juegan los CUANTOS más respaldados:
cada lotería que trae un número le da puntos según su puesto en la indicación
(ella misma 4, la 2.ª 3, la 3.ª 2, la 4.ª 1).
"""

from __future__ import annotations

from datetime import date, timedelta

CUANTOS = 6  # números (cada uno con su V) que se juegan por lotería

# Desarrollo de los números del 1 al 100, como está en la guía. El 100 de la guía es el 00.
# (En el 98 la guía dice "43,4,02": se toma como 04.)
_GUIA = """
01:10,00,68  02:79,24,70  03:80,50,07  04:95,14,31  05:69,56,02  06:15,60,23  07:70,30,08
08:80,09,49  09:90,08,71  10:01,00,68  11:66,99,76  12:67,13,21  13:37,76,71  14:65,24,34
15:85,06,14  16:32,04,08  17:34,79,47  18:36,39,98  19:46,90,31  20:98,10,63  21:31,67,12
22:77,32,09  23:60,63,78  24:79,14,34  25:07,52,96  26:20,92,62  27:41,34,87  28:82,12,38
29:30,73,92  30:85,15,70  31:21,67,86  32:16,62,38  33:18,88,38  34:24,14,27  35:36,65,75
36:18,63,93  37:13,73,93  38:62,32,68  39:40,84,34  40:04,95,90  41:81,65,14  42:97,67,79
43:34,39,84  44:96,79,04,22  45:74,70,90  46:91,93,84  47:48,74,45  48:23,93,47  49:08,94,24
50:03,07,05  51:15,60,58  52:25,07,26  53:09,35,08  54:45,70,34  55:45,66,65  56:05,95,89
57:75,01,20  58:85,03,15  59:95,04,14  60:23,06,15  61:16,19,11,66  62:32,26,68  63:36,18,39
64:19,27,87  65:10,56,95  66:11,99,16  67:12,13,76  68:01,13,86  69:05,14,96  70:25,07,20
71:09,12,67  72:27,14,06  73:30,28,32  74:45,29,42  75:35,20,52  76:13,11,67,12  77:22,72,07
78:87,32,73  79:02,17,24  80:10,90,08  81:41,63,18  82:28,12,38  83:80,39,38  84:40,39,46
85:15,58,03  86:31,68,01  87:78,32,23  88:31,33,38  89:90,34,02  90:80,09,95  91:64,93,48
92:29,62,56  93:48,36,73  94:47,49,43  95:59,40,90  96:41,69,44  97:17,31,42  98:43,04,02
99:66,11,01  00:10,98,50
""".split()

LIBRO: dict[str, list[str]] = {c[:2]: c[3:].split(",") for c in _GUIA}

# Los palés "de fuego" que marca la guía, por el número que los trae
PALES: dict[str, list[tuple[str, ...]]] = {
    "06": [("06", "15")],
    "12": [("12", "13")],
    "18": [("36", "18")],
    "25": [("07", "25")],
    "36": [("18", "36")],
    "40": [("04", "95")],
    "46": [("46", "91")],
    "52": [("25", "07")],
    "59": [("95", "04")],
    "61": [("16", "66"), ("16", "19"), ("16", "11"), ("11", "66"), ("16", "11", "66")],  # el último es tripleta
    "63": [("36", "18")],
    "78": [("87", "32")],
}

# Las loterías de la guía (como se muestra, nombres en la base de datos)
FAMILIAS: dict[str, list[str]] = {
    "Nacional": ["Lotería Nacional", "Gana Más"],
    "La Primera": ["La Primera Día", "Primera Noche"],
    "New York": ["New York Tarde", "New York Noche"],
    "Leidsa": ["Quiniela Leidsa"],
    "Real": ["Quiniela Real", "Lotería Real Noche"],
    "Loteka": ["Quiniela Loteka Día", "Quiniela Loteka Noche"],
}
FAMILIA_DE = {n: f for f, nombres in FAMILIAS.items() for n in nombres}
# Según el video, las que más premios han dado con la guía
MAS_FUERTES = {"La Primera", "Nacional", "New York"}

# "¿Dónde sale la secuencia de los números que salen en ...?" (en orden, como en la guía)
INDICA: dict[str, list[str]] = {
    "Loteka": ["Loteka", "La Primera", "Leidsa", "Nacional"],
    "La Primera": ["La Primera", "Loteka", "Nacional", "Real"],
    "New York": ["New York", "Nacional", "Leidsa", "Loteka"],
    "Nacional": ["Nacional", "Leidsa", "New York", "Loteka"],
    "Leidsa": ["Leidsa", "Nacional", "Real", "Loteka"],
    "Real": ["Real", "Nacional", "Leidsa", "New York"],
}
PESO = (4, 3, 2, 1)  # puntos según el puesto en la indicación


def de_donde(familia: str) -> list[tuple[str, int]]:
    """Las familias cuya secuencia sale en `familia`, con su puesto (0 = ella misma)."""
    return sorted(((f, lista.index(familia)) for f, lista in INDICA.items() if familia in lista),
                  key=lambda x: (x[1], x[0]))


def inverso(n: str) -> str:
    return n[::-1]


def jugar(destino: str, dia: date, buscar) -> dict:
    """La jugada de la guía para la lotería `destino` el día `dia`.

    `buscar(loteria, fecha)` devuelve el Sorteo de esa lotería ese día, o None.
    Solo se miran los dos días anteriores: lo de ayer va en su 2.º día y lo de anteayer
    en su 3.er día (el último), salvo que ya haya salido ayer en `destino` (se cerró).
    """
    ayer = buscar(destino, dia - timedelta(days=1))
    cerrados = set(ayer.numeros) if ayer else set()
    puntos: dict[str, int] = {}
    traen: dict[str, list[dict]] = {}
    mejor_dia: dict[str, int] = {}
    abiertas, pales = [], []
    for familia, puesto in de_donde(FAMILIA_DE[destino]):
        for loteria in FAMILIAS[familia]:
            for atras in (1, 2):
                s = buscar(loteria, dia - timedelta(days=atras))
                if not s:
                    continue
                dia_guia = atras + 1
                abiertas.append({"loteria": loteria, "familia": familia, "puesto": puesto + 1,
                                 "fecha": s.fecha.isoformat(), "dia": dia_guia, "numeros": list(s.numeros),
                                 "secuencias": [{"primero": p, "jala": LIBRO[p]}
                                                for p in dict.fromkeys(s.numeros) if p in LIBRO]})
                for p in dict.fromkeys(s.numeros):
                    # Palés: solo los que trae lo que salió ayer en la misma lotería
                    for par in PALES.get(p, []) if atras == 1 and puesto == 0 else []:
                        if par not in pales:
                            pales.append(par)
                    for n in LIBRO.get(p, []):
                        if atras == 2 and n in cerrados:
                            continue
                        puntos[n] = puntos.get(n, 0) + PESO[puesto]
                        traen.setdefault(n, []).append({"primero": p, "loteria": loteria, "dia": dia_guia})
                        mejor_dia[n] = min(mejor_dia.get(n, 9), dia_guia)

    elegidos = sorted(puntos, key=lambda n: (-puntos[n], mejor_dia[n], -len(traen[n]), n))[:CUANTOS]
    return {
        "jugada": [{"numero": n, "inverso": inverso(n) if inverso(n) != n else None, "puntos": puntos[n],
                    "dia": mejor_dia[n], "traen": traen[n]} for n in elegidos],
        "abiertas": abiertas,
        "pales": [list(p) for p in pales],
    }
