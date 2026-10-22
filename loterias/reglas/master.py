"""Master: el libro "Master KA" (capítulos 12 a 12.5).

El libro tiene una fila por número del 00 al 99. Cada fila son 4 números que salen
de uno solo: se le suma 5 a la primera cifra, a la segunda o a las dos
(10 -> 10, 15, 60, 65). Por eso aquí se guarda solo el primero de cada fila.

Seguimiento: el 1er premio de la Nacional Noche señala su fila, y esos 4 números
(ningún otro) se siguen al día siguiente en Gana Más, Real Día, Loteka Noche y Leidsa.

    Ejemplo (capítulo 12): Nacional Noche sale 01  ->  seguir 10, 15, 60 y 65
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from ..db import Sorteo
from .base import Contexto, Regla

DISPARADOR = "Lotería Nacional"   # Nacional Noche: solo cuenta su 1er premio
# (como se muestra, nombre en la base de datos)
DESTINOS = [
    ("Gana Más", "Gana Más"),
    ("Real Día", "Quiniela Real"),
    ("Loteka Noche", "Quiniela Loteka Noche"),
    ("Leidsa", "Quiniela Leidsa"),
]
NOMBRES = [n for _, n in DESTINOS]
PROB_AZAR = 1 - 0.99 ** 3
SUAVIZADO = 20  # seguimientos que "vale" la probabilidad general frente a los datos del libro

# Número que sale -> primer número de su fila en el libro
_PRIMERO_DE_FILA = """
01 10  02 14  03 01  04 11  05 02  06 21  07 13  08 21  09 21  10 10
11 14  12 31  13 11  14 20  15 20  16 22  17 04  18 13  19 41  20 14
21 43  22 11  23 04  24 13  25 04  26 12  27 43  28 23  29 11  30 22
31 41  32 24  33 13  34 01  35 03  36 22  37 34  38 43  39 41  40 11
41 41  42 12  43 10  44 12  45 23  46 02  47 43  48 40  49 41  50 02
51 00  52 22  53 04  54 10  55 10  56 32  57 04  58 01  59 04  60 10
61 03  62 02  63 01  64 23  65 14  66 42  67 42  68 01  69 00  70 13
71 00  72 31  73 11  74 41  75 41  76 12  77 11  78 11  79 04  80 21
81 02  82 02  83 32  84 01  85 02  86 11  87 00  88 31  89 03  90 20
91 10  92 34  93 30  94 42  95 44  96 02  97 04  98 40  99 01  00 10
""".split()


def _fila(n: str) -> list[str]:
    """"10" -> ["10", "15", "60", "65"]."""
    d, u = int(n[0]), int(n[1])
    return [f"{d}{u}", f"{d}{(u + 5) % 10}", f"{(d + 5) % 10}{u}", f"{(d + 5) % 10}{(u + 5) % 10}"]


LIBRO = {n: _fila(p) for n, p in zip(_PRIMERO_DE_FILA[::2], _PRIMERO_DE_FILA[1::2])}


def disparo(nacional: dict[date, str], fecha: date) -> str | None:
    """El 1er premio de la Nacional Noche del día anterior a `fecha`."""
    return nacional.get(fecha - timedelta(days=1))


@dataclass
class Seguido:
    numero: str
    veces: int           # veces que salió en esa lotería (en cualquier premio)
    sugerido: int        # días en que el libro lo mandó a seguir
    acerto: int          # ... y salió en esa lotería
    hace: int | None     # días desde la última vez que salió en esa lotería
    probabilidad: float  # de salir mañana en esa lotería


def seguimiento(fila: list[str], nacional: dict[date, str], historial: list[Sorteo],
                fecha: date) -> list[Seguido]:
    """Los números de la fila, de más a menos probable en la lotería de `historial`.

    La probabilidad junta dos cosas, de modo que con pocos datos manda la general:
      general     = cuánto sale ese número en esa lotería (ajustado hacia el azar, 2,97 %)
      seguimiento = de las veces que el libro lo mandó a seguir allí, cuántas salió
      probabilidad = (aciertos + SUAVIZADO * general) / (veces indicado + SUAVIZADO)
    """
    veces, sugerido, acerto = Counter(), Counter(), Counter()
    ultima: dict[str, date] = {}
    for s in historial:
        veces.update(s.numeros)
        for n in s.numeros:
            ultima[n] = s.fecha
        t = disparo(nacional, s.fecha)
        if t is not None:
            for n in LIBRO[t]:
                sugerido[n] += 1
                acerto[n] += n in s.numeros
    salida = []
    for n in fila:
        general = (veces[n] + 100 * PROB_AZAR) / (len(historial) + 100)
        prob = (acerto[n] + SUAVIZADO * general) / (sugerido[n] + SUAVIZADO)
        salida.append(Seguido(n, veces[n], sugerido[n], acerto[n],
                              (fecha - ultima[n]).days if n in ultima else None, prob))
    return sorted(salida, key=lambda x: (-x.probabilidad, x.numero))


class FilaMaster(Regla):
    nombre = "Master"
    descripcion = "La fila del libro Master KA para el último 1er premio de esta lotería."

    def predecir(self, ctx: Contexto) -> list[str]:
        return LIBRO[ctx.ultimo.numeros[0]]


REGLAS = [FilaMaster()]
