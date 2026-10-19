"""Reglas de ejemplo. Sirven de modelo para escribir las tuyas en mis_reglas.py."""

from .base import Contexto, Regla, espejo, limpiar


class EspejoDelUltimo(Regla):
    nombre = "Espejo del último"
    descripcion = "Juega el espejo de los números del sorteo anterior (23 -> 32)."

    def predecir(self, ctx: Contexto) -> list[str]:
        return limpiar(espejo(n) for n in ctx.ultimo.numeros)


class Calientes(Regla):
    nombre = "Calientes (últimos 30)"
    descripcion = "Los 3 números que más han salido en los últimos 30 sorteos."
    minimo_historial = 30

    def predecir(self, ctx: Contexto) -> list[str]:
        return [n for n, _ in ctx.frecuencias(30).most_common(3)]


class Atrasados(Regla):
    nombre = "Atrasados"
    descripcion = "Los 3 números que más sorteos llevan sin salir."
    minimo_historial = 30

    def predecir(self, ctx: Contexto) -> list[str]:
        sin_salir = ctx.dias_sin_salir()
        return sorted(sin_salir, key=lambda n: (-sin_salir[n], n))[:3]


REGLAS = [EspejoDelUltimo(), Calientes(), Atrasados()]
