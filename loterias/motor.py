"""Aplica las reglas: predicciones para un día y prueba con sorteos pasados."""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .db import Sorteo
from .reglas import Contexto, Regla

# Probabilidad de que UN número concreto salga en una quiniela de 3 números
# (cada premio es un sorteo independiente del 00 al 99).
PROB_AZAR = 1 - 0.99 ** 3  # ≈ 2.97 %


def _por_loteria(sorteos: list[Sorteo]) -> dict[str, list[Sorteo]]:
    grupos: dict[str, list[Sorteo]] = defaultdict(list)
    for s in sorteos:
        grupos[s.loteria].append(s)
    return grupos


def _ejecutar(regla: Regla, ctx: Contexto) -> list[str] | None:
    if len(ctx.historial) < regla.minimo_historial:
        return None
    try:
        return regla.predecir(ctx) or None
    except Exception as e:  # una regla con error no debe tumbar todo
        print(f"  Error en la regla '{regla.nombre}' ({ctx.loteria}): {e}")
        return None


# ---------------------------------------------------------------- predicción

@dataclass
class Prediccion:
    loteria: str
    regla: str
    numeros: list[str]


def predecir(todos: list[Sorteo], reglas: list[Regla], fecha: date) -> list[Prediccion]:
    previos = [s for s in todos if s.fecha < fecha]
    salida = []
    for loteria, historial in sorted(_por_loteria(previos).items()):
        for regla in reglas:
            if not regla.aplica_a(historial[-1]):
                continue
            ctx = Contexto(loteria, fecha, historial, previos)
            numeros = _ejecutar(regla, ctx)
            if numeros:
                salida.append(Prediccion(loteria, regla.nombre, numeros))
    return salida


# ------------------------------------------------------------ prueba histórica

@dataclass
class Resultado:
    regla: str
    jugadas: int = 0            # sorteos en los que la regla dio números
    numeros_jugados: int = 0    # total de números apostados
    aciertos: int = 0           # números jugados que salieron
    jugadas_con_acierto: int = 0
    esperado_azar: float = 0.0  # aciertos que daría jugar números al azar
    detalle: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))

    @property
    def tasa(self) -> float:
        return self.aciertos / self.numeros_jugados if self.numeros_jugados else 0.0

    @property
    def vs_azar(self) -> float:
        """1.0 = igual que el azar; 1.2 = 20 % mejor; 0.8 = 20 % peor."""
        return self.aciertos / self.esperado_azar if self.esperado_azar else 0.0

    @property
    def z(self) -> float:
        """Qué tan lejos del azar está el resultado. Entre -2 y +2 es suerte normal."""
        var = self.numeros_jugados * PROB_AZAR * (1 - PROB_AZAR)
        return (self.aciertos - self.esperado_azar) / math.sqrt(var) if var else 0.0

    def anotar(self, loteria: str, numeros: list[str], salidos: set[str]) -> int:
        aciertos = sum(1 for n in numeros if n in salidos)
        self.jugadas += 1
        self.numeros_jugados += len(numeros)
        self.aciertos += aciertos
        self.jugadas_con_acierto += aciertos > 0
        self.esperado_azar += len(numeros) * PROB_AZAR
        self.detalle[loteria][0] += len(numeros)
        self.detalle[loteria][1] += aciertos
        return aciertos


# ------------------------------------------------------------------ el Oráculo
#
# Combina todas las reglas. Cada regla "vota" por sus números con un peso que
# depende de cómo le ha ido últimamente comparada con el azar:
#     peso = (aciertos + SUAVIZADO) / (aciertos_esperados_al_azar + SUAVIZADO)
# Una regla que acierta como el azar pesa 1; una que acierta el doble, ~2.
# Cada día lo aprendido se multiplica por OLVIDO, así que el Oráculo se adapta
# a lo reciente. Juega los JUGADAS_ORACULO números con más votos.

ORACULO = "Oráculo"
OLVIDO = 0.97
SUAVIZADO = 3.0
JUGADAS_ORACULO = 3


@dataclass
class Jugada:
    numero: str
    fuerza: float          # parte del peso total de las reglas que respalda este número (0 a 1)
    reglas: list[str]      # reglas que lo recomiendan


class Memoria:
    """Lo que el Oráculo recuerda de cada regla."""

    def __init__(self):
        self.aciertos: dict[str, float] = defaultdict(float)
        self.esperado: dict[str, float] = defaultdict(float)

    def peso(self, regla: str) -> float:
        return (self.aciertos[regla] + SUAVIZADO) / (self.esperado[regla] + SUAVIZADO)

    def anotar(self, regla: str, numeros: list[str], salidos: set[str]):
        self.aciertos[regla] += sum(1 for n in numeros if n in salidos)
        self.esperado[regla] += len(numeros) * PROB_AZAR

    def olvidar(self):
        for d in (self.aciertos, self.esperado):
            for k in d:
                d[k] *= OLVIDO


def oraculo(predicciones: dict[str, list[str]], pesos: dict[str, float],
            n: int = JUGADAS_ORACULO) -> list[Jugada]:
    """Combina las predicciones de varias reglas en las n jugadas más respaldadas."""
    puntos: dict[str, float] = defaultdict(float)
    apoyo: dict[str, list[str]] = defaultdict(list)
    for regla, numeros in predicciones.items():
        for num in numeros:
            puntos[num] += pesos.get(regla, 1.0)
            apoyo[num].append(regla)
    total = sum(pesos.get(r, 1.0) for r in predicciones) or 1.0
    mejores = sorted(puntos, key=lambda x: (-puntos[x], -len(apoyo[x]), x))[:n]
    return [Jugada(x, puntos[x] / total, apoyo[x]) for x in mejores]


@dataclass
class Simulacion:
    resultados: dict[str, Resultado]      # cada regla y el Oráculo
    pesos: dict[str, float]               # lo que el Oráculo aprendió al final
    serie: list[tuple[date, int, float]]  # Oráculo por día: (fecha, aciertos, esperado al azar)


def simular(todos: list[Sorteo], reglas: list[Regla], desde: date | None = None,
            loterias: list[str] | None = None) -> Simulacion:
    """Simula haber jugado cada regla y el Oráculo en el pasado, día a día, sin ver el futuro."""
    todos = sorted(todos, key=lambda s: s.fecha)
    fechas = [s.fecha for s in todos]
    resultados = {r.nombre: Resultado(r.nombre) for r in reglas}
    resultados[ORACULO] = Resultado(ORACULO)
    memoria = Memoria()
    historial: dict[str, list[Sorteo]] = defaultdict(list)
    serie = []

    i = 0
    while i < len(todos):
        fecha = todos[i].fecha
        j = bisect.bisect_right(fechas, fecha, i)
        del_dia = todos[i:j]
        if not desde or fecha >= desde:
            previos = todos[:i]
            pesos = {r.nombre: memoria.peso(r.nombre) for r in reglas}
            aprendido = []
            aciertos_dia, esperado_dia = 0, 0.0
            for real in del_dia:
                h = historial[real.loteria]
                if not h or (loterias and real.loteria not in loterias):
                    continue
                ctx = Contexto(real.loteria, fecha, h, previos)
                salidos = set(real.numeros)
                preds = {}
                for regla in reglas:
                    if regla.aplica_a(real):
                        numeros = _ejecutar(regla, ctx)
                        if numeros:
                            preds[regla.nombre] = numeros
                            resultados[regla.nombre].anotar(real.loteria, numeros, salidos)
                            aprendido.append((regla.nombre, numeros, salidos))
                if preds:
                    jugadas = [x.numero for x in oraculo(preds, pesos)]
                    aciertos_dia += resultados[ORACULO].anotar(real.loteria, jugadas, salidos)
                    esperado_dia += len(jugadas) * PROB_AZAR
            # Al cerrar el día, el Oráculo aprende de los resultados
            for regla, numeros, salidos in aprendido:
                memoria.anotar(regla, numeros, salidos)
            memoria.olvidar()
            if esperado_dia:
                serie.append((fecha, aciertos_dia, esperado_dia))
        for real in del_dia:
            historial[real.loteria].append(real)
        i = j

    return Simulacion(resultados, {r.nombre: memoria.peso(r.nombre) for r in reglas}, serie)


def probar(todos: list[Sorteo], reglas: list[Regla], desde: date | None = None,
           loterias: list[str] | None = None) -> list[Resultado]:
    """Resultado de cada regla (y del Oráculo, al final) en los sorteos pasados."""
    return list(simular(todos, reglas, desde, loterias).resultados.values())
