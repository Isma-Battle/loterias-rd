"""Loterías indicadas: la metodología del Libro de Rosita y del Libro oculto.

Cuatro fuentes, cada una es una regla normal (así la prueba histórica las mide):

    Rosita · día      los números de cada día de la semana
    Rosita · fecha    los números de cada día del mes
    Rosita · repite   "cuando sale el 05 repite como 50 y 05"...
    Libro oculto      secuencias: cuando sale el primer número, vienen los demás

Una "v" después del número es voltearlo: se juega también al revés (23 -> 32).
La regla "Loterías indicadas" junta las cuatro y juega los números en que más coinciden.

No están en el Oráculo (reglas/__init__.py); para añadirlas, suma REGLAS a TODAS.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .base import Contexto, Regla, espejo, limpiar

# (como se muestra, nombre en la base de datos), en el orden de la sección
INDICADAS = [
    ("Primera", "La Primera Día"), ("Primera", "Primera Noche"),
    ("Suerte", "La Suerte 12:30"), ("Suerte", "La Suerte 18:00"),
    ("Real", "Quiniela Real"),
    ("Nueva York", "New York Tarde"), ("Nueva York", "New York Noche"),
    ("Leidsa", "Quiniela Leidsa"),
    ("Nacional", "Lotería Nacional"),
    ("Gana Más", "Gana Más"),
]
NOMBRES = [n for _, n in INDICADAS]
JUGADAS = 3
PROB_PRIMERO = 0.01  # un número concreto en el 1er premio


def jugar(texto: str, voltear: bool = False) -> list[str]:
    """"69v 61 09v" -> ["69", "96", "61", "09", "90"]."""
    salida = []
    for t in texto.replace("-", " ").split():
        n = t.rstrip("vV").zfill(2)
        salida += [n, espejo(n)] if voltear or t[-1] in "vV" else [n]
    return limpiar(salida)


# ------------------------------------------------------------ Libro de Rosita

# Lunes a domingo. "Aplica la V para un mejor resultado": todos se voltean.
POR_DIA = [jugar(t, voltear=True) for t in [
    "70 80 32 87 77 88",
    "50 60 56 95 55 66 99",
    "40 70 35 47 44 77",
    "30 50 80 38 58 35 33 55 88",
    "01 09 19 69 46 49 00 11 99",
    "60 90 46 49 69 66 99",
    "20 30 32 78 22 33",
]]

# Día del mes (se copian tal cual del libro, con sus "v")
POR_FECHA = {dia: jugar(t) for dia, t in {
    1: "69v 61v 09v", 2: "68v 62v 08v", 3: "67v 63v 07v", 4: "65v 64v 05v",
    5: "64v 65v 04v", 6: "60v 66 00", 7: "63v 67v 03v", 8: "62v 68v 02v",
    9: "61v 69v 01v", 10: "96v 90v 16v", 11: "99 91v 01v", 12: "98v 92v 18v",
    13: "97v 93v 17v", 14: "95v 94v 15v", 15: "94v 95v 14v", 16: "90v 96v 10v",
    17: "93v 97v 13v", 18: "92v 98v 12v", 19: "91v 99 11", 20: "86v 80v 26v",
    21: "89v 81v 29v", 22: "88v 82v 72v", 23: "87v 83v 28v", 24: "85v 84v 25v",
    25: "84v 85v 24v", 26: "80v 86v 20v", 27: "83v 87v 23v", 28: "82v 87v 22",
    29: "81v 89v 21v", 30: "76v 70v 36v", 31: "79v 71v 39v",
}.items()}

# Cuando sale el primero, repite como los demás ("viceversa" va en las dos direcciones)
REPITE = {n: jugar(t) for n, t in {
    "05": "50 05", "06": "06 60", "16": "16 61", "27": "27 72", "28": "28 82",
    "37": "37 73", "38": "38 83", "45": "45 54", "49": "49 94",
    "69": "66 99", "66": "69", "99": "69",
    "01": "11 00", "11": "01", "00": "01",
}.items()}


# --------------------------------------------------------------- Libro oculto

@dataclass(frozen=True)
class Secuencia:
    texto: str                  # como está en el libro: "00-06v-10v"
    activa_con: frozenset[str]  # el primer número (y su volteo si lleva "v")
    numeros: tuple[str, ...]    # lo que se juega cuando se activa
    pales: tuple[str, ...]      # palés que el libro anota debajo: "06-00"
    nota: str = ""


def _sec(texto: str, pales: str = "", nota: str = "") -> Secuencia:
    primero, *resto = texto.split("-")
    return Secuencia(texto, frozenset(jugar(primero)), tuple(jugar(" ".join(resto))),
                     tuple(pales.split()), nota)


LIBRO = [
    _sec("00-06v-10v", "06-00 10-00 10-06"), _sec("00-45v", "00-45"),
    _sec("01v-56v", "01-56"), _sec("01-29", nota="no falla"),
    _sec("02-07-25-75", "20-07 25-70 20-25 70-75"), _sec("03v-08v-53v-58v"),
    _sec("04v-85v"), _sec("05-50"), _sec("06v-00-10v", "06-10"),
    _sec("07v-14v-25v", "07-25 07-14 14-25"), _sec("08v-90v-14v", "08-36 09-14"),
    _sec("09v-14v-08v", nota="salen en palés"), _sec("10v-36v", "10-36"),
    _sec("11-66", "11-66"), _sec("12v-36-13v", "12-36"), _sec("13v-12v"),
    _sec("14v-19v-64v-96v", nota="se ligan en palés"), _sec("15-10-65", "01-56 10-15"),
    _sec("16-66-19", "16-19 19-66 16-66"), _sec("18v-19v"), _sec("19-66-81", "19-66"),
    _sec("20-25-70-72", nota="se ligan en palés"), _sec("21-36v", "12-36"),
    _sec("22-27v-77", "27-22 22-77 27-77"), _sec("23-34", "23-34"),
    _sec("24-42", nota="voltea"), _sec("25-88-14", "25-14 25-88"), _sec("25-88"),
    _sec("26-16", nota="fuerte"), _sec("27-22-77"), _sec("28-38", "28-38"),
    _sec("29-10", nota="fuerte"), _sec("29v-39", "29-39-36", "fuerte, tripleta"),
    _sec("30v-38-88"), _sec("31-12"), _sec("32-34", "23-34"),
    _sec("33-88-38-03", "38-88 03-38"), _sec("36-00-10-21", "36-00"),
    _sec("37-45", nota="fuerte"), _sec("37v-35v"), _sec("39-36v", "36-39"),
    _sec("40v-58v"), _sec("41-46-91-96", nota="se ligan en palés"),
    _sec("44-49-99", "44-49 44-99 49-99"), _sec("45-37-00", "45-00"),
    _sec("46-41-96-91", nota="se ligan en palés"),
    _sec("47-48", "47-48", "o repite secuencia"), _sec("50-00", "50-00"),
    _sec("51-10", "15-10"), _sec("51-55-56v", "51-56"),
    _sec("52-57-02-07", nota="se ligan en palés"), _sec("55-00", "55-00"),
    _sec("56v-51", "01-56"), _sec("56-01", "01-56"), _sec("58v-04v"),
    _sec("60-10-00", "06-00 06-10"), _sec("61-62"), _sec("62-26", nota="voltea"),
    _sec("64-69-14-19", nota="todos salen en palés"), _sec("66-91-11-16v", "66-11 91-66"),
    _sec("67-79", "79-76"), _sec("68-89", "86-89"),
    _sec("70-75-25-20", nota="todos salen en palés"),
    _sec("72-77-22", nota="todos salen en palés"), _sec("73v-45v"),
    _sec("74v-84v", "47-48"), _sec("75-70-25-20"), _sec("76v-79v", "76-79"),
    _sec("77-14-66", "77-14"), _sec("80-90-41", "09-14"), _sec("81v-91v"),
    _sec("83v-28", nota="full"), _sec("84v-74v"), _sec("85v-04v"), _sec("86v-98v"),
    _sec("87-78"), _sec("88-25"), _sec("88-38-33", nota="todos salen en palés"),
    _sec("92v-10v-39v", "29-39"), _sec("93-36", "93-36"), _sec("94-99-44"),
    _sec("96-14-91-46", nota="se ligan en palés"), _sec("97-67"), _sec("98-86"),
    _sec("99-44-49"),
]


# ------------------------------------------------------------------ combinar

@dataclass
class Jugada:
    numero: str
    votos: int            # cuántas fuentes lo indican
    fuentes: list[str]


@dataclass
class Analisis:
    fuentes: dict[str, list[str]]   # fuente -> números que indica
    secuencias: list[Secuencia]     # secuencias del libro que activó el último sorteo
    jugadas: list[Jugada]           # todos los indicados, de más a menos coincidencias


def _combinar(ctx: Contexto, salidos, frec) -> Analisis:
    """Junta las cuatro fuentes disparadas por `salidos`; los empates los rompe `frec`."""
    secuencias = [s for s in LIBRO if s.activa_con.intersection(salidos)]
    fuentes = {
        "Rosita · día": POR_DIA[ctx.fecha.weekday()],
        "Rosita · fecha": POR_FECHA[ctx.fecha.day],
        "Rosita · repite": limpiar(n for x in salidos for n in REPITE.get(x, [])),
        "Libro oculto": limpiar(n for s in secuencias for n in s.numeros),
    }
    apoyo: dict[str, list[str]] = defaultdict(list)
    for fuente, numeros in fuentes.items():
        for n in numeros:
            apoyo[n].append(fuente)
    # Empates: primero los de secuencias "fuerte", luego los más salidos últimamente
    fuertes = {n for s in secuencias if "fuerte" in s.nota for n in s.numeros}
    orden = sorted(apoyo, key=lambda n: (-len(apoyo[n]), n not in fuertes, -frec[n], n))
    return Analisis(fuentes, secuencias, [Jugada(n, len(apoyo[n]), apoyo[n]) for n in orden])


def analizar(ctx: Contexto) -> Analisis:
    """Para la quiniela: lo dispara todo el último sorteo."""
    return _combinar(ctx, ctx.ultimo.numeros, ctx.frecuencias(30))


def primer_premio(ctx: Contexto) -> Analisis:
    """Solo para el 1er premio: lo dispara el 1er premio anterior, y en los empates
    pesan los números que más han salido de 1er premio en los últimos 30 sorteos."""
    frec = Counter(s.numeros[0] for s in ctx.ultimos(30))
    return _combinar(ctx, ctx.ultimo.numeros[:1], frec)


class Fuente(Regla):
    loterias = NOMBRES

    def __init__(self, nombre: str, descripcion: str):
        self.nombre, self.descripcion = nombre, descripcion

    def predecir(self, ctx: Contexto) -> list[str]:
        return analizar(ctx).fuentes[self.nombre]


class Indicadas(Regla):
    nombre = "Loterías indicadas"
    descripcion = "Los 3 números en que más coinciden las cuatro fuentes de los libros."
    loterias = NOMBRES

    def predecir(self, ctx: Contexto) -> list[str]:
        return [j.numero for j in analizar(ctx).jugadas[:JUGADAS]]


REGLAS = [
    Indicadas(),
    Fuente("Rosita · día", "Los números del día de la semana, con su volteo."),
    Fuente("Rosita · fecha", "Los números del día del mes."),
    Fuente("Rosita · repite", "Cuando sale un número, repite como su pareja."),
    Fuente("Libro oculto", "Las secuencias que se activan con el último sorteo."),
]
