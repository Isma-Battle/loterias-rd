"""Libro oculto: secuencias de números que salen juntos (en palés), por su primer número.

Cómo se usa junto al Público y VIP:

  1. Se miran los 1ros premios de los últimos DIAS_ATRAS días de cada lotería.
  2. Si un 1er premio es el primer número de una secuencia del libro, se "abren" los números
     que le siguen en esa secuencia.
  3. Los números del Público o del VIP que también están abiertos por el libro cumplen los
     dos métodos: se marcan con un fuego.

Todos los números cuentan también con su inverso (75 = 75 y 57), tanto el primero de la
secuencia como los que le siguen. La "v" del libro (06v) queda solo como anotación.
Según el libro, sus secuencias dan mejor resultado en Nacional, Florida y New York.
"""

from __future__ import annotations

from datetime import date, timedelta

DIAS_ATRAS = 2  # 1ros premios de ayer y anteayer

# Copiadas del libro en el mismo orden. "24 voltea 42" y "62 voltea 26" van como 24-42 y 62-26;
# "29v--39 se ligan en tripleta 29 39 36" va como 29v-39-36; "83v--->28 FULL" como 83v-28.
_SECUENCIAS = """
00-06v-10v  00-45v  01v-56v  01-29  02-07-25-75  03v-08v-53v-58v  04v-85v  05-50  06v-00-10v
07v-14v-25v  08v-90v-14v  09v-14v-08v  10v-36v  11-66  12v-36-13v  13v-12v  14v-19v-64v-96v
15-10-65  16-66-19  18v-19v  19-66-81  20-25-70-72  21-36v  22-27v-77  23-34  24-42  25-88-14
25-88  26-16  27-22-77  28-38  29-10  29v-39-36  30v-38-88  31-12  32-34  33-88-38-03
36-00-10-21  37-45  37v-35v  39-36v  40v-58v  41-46-91-96  44-49-99  45-37-00  46-41-96-91
47-48  50-00  51-10  51-55-56v  52-57-02-07  55-00  56v-51  56-01  58v-04v  60-10-00  61-62
62-26  64-69-14-19  66-91-11-16v  67-79  68-89  70-75-25-20  72-77-22  73v-45v  74v-84v
75-70-25-20  76v-79v  77-14-66  80-90-41  81v-91v  83v-28  84v-74v  85v-04v  86v-98v  87-78
88-25  88-38-33  92v-10v-39v  93-36  94-99-44  96-14-91-46  97-67  98-86  99-44-49
""".split()

# Las que el libro marca como fuertes ("no falla", 💪)
FUERTES = {"01-29", "26-16", "29-10", "29v-39-36", "37-45"}


def _con_v(token: str) -> list[str]:
    """El número y su inverso: '75' -> ['75', '57']; '06v' -> ['06', '60']; '44' -> ['44']."""
    n = token.rstrip("v")
    return [n, n[::-1]] if n[::-1] != n else [n]


def _leer(texto: str) -> dict:
    partes = texto.split("-")
    return {"texto": texto, "primero": _con_v(partes[0]),
            "siguen": list(dict.fromkeys(x for p in partes[1:] for x in _con_v(p))),
            "fuerte": texto in FUERTES}


LIBRO: list[dict] = [_leer(t) for t in _SECUENCIAS]


def abiertos(primeras: list[tuple[str, date, str]]) -> tuple[dict[str, list[dict]], list[dict]]:
    """`primeras`: [(loteria, fecha, 1er premio), ...] de los últimos días.

    Devuelve ({número que sigue: [de dónde viene, ...]}, [secuencias abiertas]).
    """
    numeros: dict[str, list[dict]] = {}
    abiertas: list[dict] = []
    for loteria, fecha, n in primeras:
        for sec in LIBRO:
            if n not in sec["primero"]:
                continue
            origen = {"loteria": loteria, "fecha": fecha.isoformat(), "numero": n,
                      "secuencia": sec["texto"], "fuerte": sec["fuerte"]}
            abiertas.append({**origen, "siguen": sec["siguen"]})
            for x in sec["siguen"]:
                numeros.setdefault(x, []).append(origen)
    return numeros, abiertas


def primeras_de(sorteos, dia: date, dias: int = DIAS_ATRAS) -> list[tuple[str, date, str]]:
    """Los 1ros premios de los `dias` días antes de `dia` (el más reciente primero)."""
    desde = dia - timedelta(days=dias)
    return sorted(((s.loteria, s.fecha, s.numeros[0]) for s in sorteos if desde <= s.fecha < dia and s.numeros),
                  key=lambda x: (-x[1].toordinal(), x[0]))
