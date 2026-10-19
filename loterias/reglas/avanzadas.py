"""Reglas avanzadas: cada una mira el historial desde un ángulo distinto.

Ninguna se usa sola: el Oráculo (motor.py) las combina y aprende, día a día,
cuáles vienen acertando más para darles más peso.
"""

from collections import Counter, defaultdict

from .base import Contexto, Regla, limpiar

TODOS = [f"{i:02d}" for i in range(100)]


def _raiz(x: int) -> int:
    """Suma de cifras reducida a una sola cifra (0 solo para el 0)."""
    return 9 if x and x % 9 == 0 else x % 9


class Sucesores(Regla):
    nombre = "Sucesores"
    descripcion = "Lo que suele salir en el sorteo siguiente a los números que acaban de salir."
    minimo_historial = 40

    def predecir(self, ctx: Contexto) -> list[str]:
        ultimos = set(ctx.ultimo.numeros)
        cuenta = Counter()
        h = ctx.historial
        for i in range(len(h) - 1):
            if ultimos.intersection(h[i].numeros):
                cuenta.update(h[i + 1].numeros)
        return [n for n, _ in cuenta.most_common(3)]


class RitmoPropio(Regla):
    nombre = "Ritmo propio"
    descripcion = "Cada número tiene su intervalo habitual entre salidas: juega los que ya lo pasaron."
    minimo_historial = 40

    def predecir(self, ctx: Contexto) -> list[str]:
        posiciones = defaultdict(list)
        for i, s in enumerate(ctx.historial):
            for n in set(s.numeros):
                posiciones[n].append(i)
        actual = len(ctx.historial) - 1
        retraso = {}
        for n, pos in posiciones.items():
            if len(pos) >= 3:
                medio = (pos[-1] - pos[0]) / (len(pos) - 1)
                retraso[n] = (actual - pos[-1]) / medio
        return sorted(retraso, key=lambda n: (-retraso[n], n))[:3]


class DiaDeLaSemana(Regla):
    nombre = "Día de la semana"
    descripcion = "Los números que más salen en esta lotería el mismo día de la semana."
    minimo_historial = 30

    def predecir(self, ctx: Contexto) -> list[str]:
        dia = ctx.fecha.weekday()
        c = Counter(n for s in ctx.historial if s.fecha.weekday() == dia for n in s.numeros)
        return [n for n, _ in c.most_common(3)]


class DecenaTerminacion(Regla):
    nombre = "Decena y terminación"
    descripcion = "Une la decena y la terminación más frecuentes de los últimos 20 sorteos."
    minimo_historial = 20

    def predecir(self, ctx: Contexto) -> list[str]:
        nums = [n for s in ctx.ultimos(20) for n in s.numeros]
        dec = [d for d, _ in Counter(n[0] for n in nums).most_common(2)]
        ter = [t for t, _ in Counter(n[1] for n in nums).most_common(2)]
        if len(dec) < 2 or len(ter) < 2:
            return []
        return limpiar([dec[0] + ter[0], dec[0] + ter[1], dec[1] + ter[0]])


class PulsoDelDia(Regla):
    nombre = "Pulso del día"
    descripcion = "Los números que más se repitieron ayer entre todas las loterías del país."

    def predecir(self, ctx: Contexto) -> list[str]:
        if not ctx.todas:
            return []
        ultimo_dia = ctx.todas[-1].fecha
        c = Counter()
        for s in reversed(ctx.todas):
            if s.fecha != ultimo_dia:
                break
            if s.es_quiniela:
                c.update(s.numeros)
        return [n for n, k in c.most_common(3) if k > 1]


class RaizNumerologica(Regla):
    nombre = "Raíz numerológica"
    descripcion = ("Suma las cifras del último sorteo hasta dejar una sola y juega los números "
                   "más calientes que comparten esa raíz.")
    minimo_historial = 30

    def predecir(self, ctx: Contexto) -> list[str]:
        raiz = _raiz(sum(int(c) for n in ctx.ultimo.numeros for c in n))
        frec = ctx.frecuencias(60)
        candidatos = [n for n in TODOS if _raiz(int(n[0]) + int(n[1])) == raiz]
        return sorted(candidatos, key=lambda n: (-frec[n], n))[:3]


class VecinosDelPrimero(Regla):
    nombre = "Vecinos del primero"
    descripcion = "El número anterior y el siguiente al último primer premio."

    def predecir(self, ctx: Contexto) -> list[str]:
        n = int(ctx.ultimo.numeros[0])
        return limpiar([(n - 1) % 100, (n + 1) % 100])


class Tendencia(Regla):
    nombre = "Tendencia"
    descripcion = "Números que vienen subiendo: salen más en los últimos 15 sorteos que en los 45 anteriores."
    minimo_historial = 60

    def predecir(self, ctx: Contexto) -> list[str]:
        reciente = ctx.frecuencias(15)
        antes = Counter(n for s in ctx.historial[-60:-15] for n in s.numeros)
        subida = {n: reciente[n] / 15 - antes[n] / 45 for n in reciente}
        return sorted(subida, key=lambda n: (-subida[n], n))[:3]


REGLAS = [
    Sucesores(), RitmoPropio(), DiaDeLaSemana(), DecenaTerminacion(),
    PulsoDelDia(), RaizNumerologica(), VecinosDelPrimero(), Tendencia(),
]
