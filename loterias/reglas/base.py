"""Lo que toda regla debe tener."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from ..db import Sorteo


@dataclass
class Contexto:
    """Todo lo que una regla puede consultar para hacer su predicción.

    Una regla NUNCA ve el resultado que intenta predecir: tanto `historial`
    como `todas` contienen solo sorteos de días anteriores a `fecha`.
    """
    loteria: str                 # lotería para la que se predice
    fecha: date                  # día del sorteo que se predice
    historial: list[Sorteo]      # sorteos anteriores de esa lotería (antiguo -> reciente)
    todas: list[Sorteo]          # sorteos anteriores de TODAS las loterías

    # --- Ayudas para escribir reglas rápido -------------------------------

    @property
    def ultimo(self) -> Sorteo | None:
        return self.historial[-1] if self.historial else None

    def ultimos(self, n: int) -> list[Sorteo]:
        return self.historial[-n:]

    def frecuencias(self, n: int | None = None) -> Counter:
        """Cuántas veces salió cada número en los últimos n sorteos (o en todos)."""
        sorteos = self.historial if n is None else self.historial[-n:]
        return Counter(num for s in sorteos for num in s.numeros)

    def dias_sin_salir(self) -> dict[str, int]:
        """Para cada número 00-99, cuántos sorteos lleva sin salir."""
        resultado = {f"{i:02d}": len(self.historial) for i in range(100)}
        for pos, s in enumerate(reversed(self.historial)):
            for num in s.numeros:
                resultado[num] = min(resultado[num], pos)
        return resultado

    def de_otra(self, loteria: str) -> list[Sorteo]:
        """Historial de otra lotería (por nombre exacto)."""
        return [s for s in self.todas if s.loteria == loteria]


class Regla:
    """Plantilla. Copia una regla de ejemplo y cambia lo que necesites."""

    nombre: str = "Sin nombre"
    descripcion: str = ""
    # Loterías a las que se aplica. None = todas las quinielas.
    loterias: list[str] | None = None
    # Sorteos previos que necesita la regla antes de poder predecir
    minimo_historial: int = 1

    def aplica_a(self, sorteo_ejemplo: Sorteo) -> bool:
        if not sorteo_ejemplo.es_quiniela:
            return False
        return self.loterias is None or sorteo_ejemplo.loteria in self.loterias

    def predecir(self, ctx: Contexto) -> list[str]:
        """Devuelve los números a jugar, como texto de 2 cifras: ["07", "45"]."""
        raise NotImplementedError


def espejo(numero: str) -> str:
    """23 -> 32, 07 -> 70."""
    return numero[::-1]


def limpiar(numeros) -> list[str]:
    """Quita repetidos y deja todo en formato de 2 cifras, conservando el orden."""
    vistos, salida = set(), []
    for n in numeros:
        n = f"{int(n) % 100:02d}"
        if n not in vistos:
            vistos.add(n)
            salida.append(n)
    return salida
