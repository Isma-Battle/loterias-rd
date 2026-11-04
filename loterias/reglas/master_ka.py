"""Método completo del libro "Master KA", como se explica en la clase de YouTube.

Pasos del video:
  1. Se toman los números que salieron AYER (1er premio) en Real, Nacional, Gana Más,
     Leidsa, La Primera y Nueva York.
  2. Cada uno se busca en el capítulo 5 (pág. 17), que dice qué números "trae".
     Se suman también el capítulo 6 (números que repiten) y el capítulo 12
     (familia del 1er premio de la Nacional Noche, ya en master.py).
  3. Se cuenta qué número aparece más veces: ese es el "más fuerte".
  4. Al más fuerte se le busca su palé en el capítulo 4 y en el capítulo 13 (VIP).

    Ejemplo del video: ayer salió 69  ->  capítulo 5 da 15 y 22
                       el más fuerte es 15  ->  palé 69 (cap. 4 y cap. 13)

Si alguna tabla tiene un error de copia, se corrige aquí abajo.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from .base import Contexto, Regla, espejo
from .master import DISPARADOR, LIBRO as CAPITULO_12

# Loterías cuyos números de ayer alimentan el cálculo (nombres de la base de datos)
FUENTES = [
    "Quiniela Real", "Lotería Nacional", "Gana Más", "Quiniela Leidsa",
    "La Primera Día", "Primera Noche", "New York Tarde", "New York Noche",
]
# Loterías para las que se hace la predicción ("Nacional y Real mayormente")
DESTINOS = [
    "Lotería Nacional", "Gana Más", "Quiniela Real", "Quiniela Leidsa",
    "Quiniela Loteka Noche", "La Primera Día", "Primera Noche",
]

# ------------------------------------------------------------------ tablas

# Capítulo 4, pág. 16: Tabla de Palé de Secuencia Poderosa.
# (En el libro falta el 02 y la última casilla dice "01-12"; se toma como 02-12.)
_CAP4 = """
00-25 01-28 03-11 04-91 05-32 06-15 07-12 08-57 09-27 10-00
11-45 12-66 13-63 14-69 15-69 16-61 17-30 18-76 19-36 20-02
21-71 22-01 23-74 24-29 25-00 26-21 27-09 28-01 29-31 30-17
31-29 32-05 33-98 34-17 35-70 36-19 37-39 38-83 39-37 40-95
41-02 42-97 43-23 44-85 45-11 46-21 47-57 48-43 49-25 50-25
51-17 52-02 53-35 54-04 55-65 56-12 57-08 58-08 59-04 60-66
61-07 62-12 63-13 64-04 65-55 66-12 67-04 68-15 69-22 70-35
71-21 72-89 73-18 74-23 75-75 76-18 77-30 78-73 79-24 80-08
81-25 82-87 83-38 84-89 85-14 86-23 87-04 88-33 89-72 90-85
91-04 92-42 93-43 94-49 95-40 96-15 97-42 98-72 99-01 02-12
"""

# Capítulo 5, pág. 17: Conocimientos del Máster Ka. El primero de cada fila "trae" a los demás.
# (El 20 no tiene fila propia: se usa la fila 02-20-14-41, como en el video.)
_CAP5 = """
00-81-49-25 01-10-28-68 02-20-14-41 03-15-11 04-91 05-32-23 06-15-51 07-17-19 08-57-80 09-27
10-01-28-68 11-45 12-56-66 13-39-63 14-41-02-20 15-22-69 16-61 17-30-51 18-73-76 19-36
20-02-14-41 21-46-71 22-15-69 23-74 24-14-34 25-81-49-00 26-62-29 27-09 28-01-10 29-31
30-51-17 31-29 32-05-23 33-98-89 34-14-24 35-53-70 36-19 37-73-39-93 38-83-88 39-37-73-93
40-59-95-65 41-02-20-14 42-97-47 43-34-17 44-85-90 45-11-10 46-47-56-57 47-56-46-57 48-63 49-94-14
50-05 51-17-30 52-13-38 53-35-70 54-04 55-65 56-12-66 57-64-46 58-34 59-10
60-06-15 61-16 62-26 63-13-39 64-46-57 65-55 66-12-56 67-04-78 68-01-10-28 69-15-22
70-35 71-21-46 72-89 73-37 74-23 75-25 76-18-73 77-30 78-04-67 79-04
80-08-88 81-25 82-41 83-38-88 84-04-43 85-90-44 86-74-23 87-04-15 88-38-83 89-72
90-44 91-04 92-12 93-39-37-73 94-49-25 95-40 96-16 97-42 98-33 99-00
"""

# Capítulo 6, pág. 18: números que cuando salen se repiten con frecuencia (pares de volteo).
_CAP6 = """
01-10 02-20 03-30 04-40 05-50 07-70 09-90 11-11 12-21 13-31 17-71 19-91 23-32
25-52 27-72 29-92 33-33 35-53 37-73 39-93 43-34 49-94 55-55 57-75 59-95 18-81
"""

# Capítulo 13, pág. 29: Lista fuerte de palé VIP.
_CAP13 = """
01-28 02-41 03-11 04-91 05-32 06-15 07-12 08-57 09-27 10-00
11-45 12-66 13-63 14-69 15-69 16-88 17-30 18-76 19-36 20-91
21-71 22-01 23-74 24-98 25-00 26-95 27-38 28-68 29-31 30-51
31-04 32-79 33-98 34-17 35-70 36-39 37-62 38-88 39-37 40-95
41-02 42-98 43-23 44-90 45-11 46-21 47-97 48-12 49-25 50-19
51-17 52-02 53-52 54-04 55-19 56-12 57-08 58-08 59-10 60-15
61-07 62-12 63-39 64-25 65-95 66-03 67-40 68-10 69-22 70-35
71-46 72-89 73-18 74-86 75-57 76-73 77-30 78-28 79-04 80-60
81-25 82-41 83-88 84-04 85-14 86-10 87-15 88-08 89-09 90-85
91-05 92-03 93-73 94-25 95-40 96-08 97-07 98-20 99-01 00-49
"""


def _filas(texto: str) -> dict[str, list[str]]:
    """'15-22-69' -> {'15': ['22', '69']}."""
    tabla = {}
    for celda in texto.split():
        primero, *resto = celda.split("-")
        tabla[primero] = resto
    return tabla


CAPITULO_4 = _filas(_CAP4)
CAPITULO_5 = _filas(_CAP5)
CAPITULO_13 = _filas(_CAP13)
CAPITULO_6 = {}
for _a, _b in (c.split("-") for c in _CAP6.split()):
    CAPITULO_6[_a], CAPITULO_6[_b] = _b, _a


# ----------------------------------------------------------------- cálculo

def numeros_de_ayer(ctx: Contexto) -> dict[str, str]:
    """1er premio de ayer de cada lotería fuente: {"Quiniela Real": "20", ...}."""
    ayer = ctx.fecha - timedelta(days=1)
    salida = {}
    for s in reversed(ctx.todas):  # `todas` va de antiguo a reciente
        if s.fecha < ayer:
            break
        if s.fecha == ayer and s.loteria in FUENTES and s.numeros:
            salida.setdefault(s.loteria, s.numeros[0])
    return salida


def conteo(ayer: dict[str, str]) -> Counter:
    """Cuántas veces señalan las tablas a cada número (capítulos 5, 6 y 12)."""
    veces = Counter()
    for n in ayer.values():
        veces.update(CAPITULO_5.get(n, []))
        if n in CAPITULO_6:
            veces.update([n, CAPITULO_6[n]])
    if DISPARADOR in ayer:
        veces.update(CAPITULO_12[ayer[DISPARADOR]])
    return veces


def mas_fuertes(veces: Counter, cuantos: int) -> list[str]:
    """Los más repetidos; en empate, el número menor (para que sea siempre igual)."""
    return [n for n, _ in sorted(veces.items(), key=lambda x: (-x[1], x[0]))[:cuantos]]


def pales(numero: str) -> list[str]:
    """Compañeros de palé del capítulo 4 y del capítulo 13."""
    salida = []
    for tabla in (CAPITULO_4, CAPITULO_13):
        for p in tabla.get(numero, []):
            if p not in salida and p != numero:
                salida.append(p)
    return salida


# ------------------------------------------------------------------ reglas

class MasterFuerte(Regla):
    nombre = "Master KA fuerte"
    descripcion = ("Los 3 números que más señalan los capítulos 5, 6 y 12 "
                   "a partir de los primeros premios de ayer.")
    loterias = DESTINOS

    def predecir(self, ctx: Contexto) -> list[str]:
        return mas_fuertes(conteo(numeros_de_ayer(ctx)), 3)


class MasterPale(Regla):
    nombre = "Master KA palé"
    descripcion = "El número más fuerte y sus palés de los capítulos 4 y 13."
    loterias = DESTINOS

    def predecir(self, ctx: Contexto) -> list[str]:
        fuerte = mas_fuertes(conteo(numeros_de_ayer(ctx)), 1)
        return fuerte + pales(fuerte[0]) if fuerte else []


class MasterRepiten(Regla):
    nombre = "Master KA repiten"
    descripcion = "Capítulo 6: si ayer salió un número de la lista, se juega él y su volteo."
    loterias = DESTINOS

    def predecir(self, ctx: Contexto) -> list[str]:
        salida = []
        for n in numeros_de_ayer(ctx).values():
            if n in CAPITULO_6:
                for x in (n, CAPITULO_6[n]):
                    if x not in salida:
                        salida.append(x)
        return salida


REGLAS = [MasterFuerte(), MasterPale(), MasterRepiten()]

# Comprobación: cada tabla de 00 a 99 está completa
assert len(CAPITULO_4) == len(CAPITULO_5) == len(CAPITULO_13) == 100
assert all(CAPITULO_6[n] == espejo(n) for n in CAPITULO_6)
