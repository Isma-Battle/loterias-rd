"""Interfaz web local para ver los resultados guardados.

    python main.py web      ->  abre http://localhost:8000 en el navegador

Solo usa la librería estándar de Python. La página está en loterias/web/index.html
y pide los datos a estas rutas (todas devuelven JSON):

    GET  /api/resumen                    loterías guardadas y rango de fechas
    GET  /api/dia?fecha=AAAA-MM-DD       todos los resultados de un día
    GET  /api/loteria?nombre=...&n=60    historial y estadísticas de una lotería
    GET  /api/recomendaciones?fecha=...  números recomendados por las reglas para ese día
         (&loteria=... para una sola)
    GET  /api/indicadas?fecha=...        loterías indicadas según el Libro de Rosita y el Libro oculto
    GET  /api/fuertes?fecha=...          las 7 parejas número-inverso que más han salido en 3 años en cada indicada,
                                         más Real Noche, Loteka, King Lottery y Florida (Día y Noche)
    GET  /api/master?fecha=...           la fila del libro Master KA para el 1er premio de la Nacional Noche,
                                         seguida en Gana Más, Real Día, Loteka Noche y Leidsa
    GET  /api/king?fecha=...             Master King: el último sorteo de cada lotería abre sus filas de los
                                         capítulos 05 y 07 del Máster Ka; se juegan los 4 que más han salido
    GET  /api/raya?fecha=...             3 en raya: los campos del capítulo 05 del Máster Ka que abre el último
                                         sorteo, en las mismas loterías que los 7 más fuertes
    GET  /api/josefina?fecha=...         Guía Josefina: lo que salió ayer en las loterías indicadas jala su
                                         secuencia; se juegan los 6 más respaldados con su V
    GET  /api/vip?fecha=...              Público y VIP: las 7 parejas más fuertes en 1er premio de 10 loterías
                                         juntas; las 4 primeras son del Público y las otras 3 del VIP. Los
                                         que además abre el Libro oculto (1ros premios de 3 días) llevan fuego
    GET  /api/formula?fecha=...          La Fórmula: 6 números de la Anguila de las 10 AM (1·23·2 -> 12 32) y en
                                         qué loterías de ese día han salido más de 1er premio
    GET  /api/laboratorio?fecha=...      Laboratorio: los números en que más métodos coinciden, El Vigilante
                                         (busca máquinas sesgadas) y la tabla de la verdad de cada método
    GET  /api/compartir?metodo=...&fecha=...  los números de un método en filas, para la imagen de WhatsApp
    GET  /flyer_gratis.jpg, /flyer_vip.jpg   los flyers del Público y VIP (se les cambian números y fecha)
    GET  /plantilla.png                  la imagen modelo para compartir (loterias/web/plantilla.png), si existe
    POST /api/actualizar                 descarga los resultados de hoy y ayer
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
import webbrowser
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, motor, recolector
from .reglas import TODAS as REGLAS
from .reglas import Contexto
from .reglas import indicadas as libro
from .reglas import master as libro_master
from .reglas import formula as libro_formula
from .reglas import raya as libro_raya
from .reglas import king as libro_king
from .reglas import josefina as libro_josefina
from .reglas import oculto as libro_oculto
from .reglas import vigilante as libro_vigilante

PAGINA = Path(__file__).resolve().parent / "web" / "index.html"

# Orden en que se muestran las loterías (las que no estén aquí van al final)
ORDEN_GRUPOS = [
    "Nacional", "Leidsa", "Loteria Real", "Loteka", "La Primera", "La Suerte",
    "LoteDom", "Anguila", "King Lottery", "Americanas", "Nueva York", "Florida",
    "Haiti Bolet",
]


def _orden(grupo: str):
    return (ORDEN_GRUPOS.index(grupo) if grupo in ORDEN_GRUPOS else len(ORDEN_GRUPOS), grupo)


def _agrupar(filas) -> list[dict]:
    """[(grupo, dict), ...] -> [{"grupo": ..., "loterias": [dict, ...]}, ...] en orden."""
    grupos: dict[str, list[dict]] = {}
    for grupo, item in filas:
        grupos.setdefault(grupo, []).append(item)
    return [{"grupo": g, "loterias": sorted(grupos[g], key=lambda x: x["nombre"])}
            for g in sorted(grupos, key=_orden)]


# ------------------------------------------------------------------ consultas

def resumen(con) -> dict:
    filas = list(con.execute(
        "SELECT loteria, grupo, COUNT(*), MAX(fecha) FROM sorteos GROUP BY loteria, grupo"))
    rango = con.execute("SELECT MIN(fecha), MAX(fecha), COUNT(*) FROM sorteos").fetchone()
    return {
        "desde": rango[0], "hasta": rango[1], "total": rango[2],
        "grupos": _agrupar((g, {"nombre": l, "sorteos": n, "ultimo": u}) for l, g, n, u in filas),
    }


def dia(con, fecha: date) -> dict:
    iso = fecha.isoformat()
    filas = con.execute("SELECT loteria, grupo, numeros FROM sorteos WHERE fecha = ?", (iso,))
    anterior = con.execute("SELECT MAX(fecha) FROM sorteos WHERE fecha < ?", (iso,)).fetchone()[0]
    siguiente = con.execute("SELECT MIN(fecha) FROM sorteos WHERE fecha > ?", (iso,)).fetchone()[0]
    return {
        "fecha": iso, "anterior": anterior, "siguiente": siguiente,
        "grupos": _agrupar((g, {"nombre": l, "numeros": n.split("-")}) for l, g, n in filas),
    }


def loteria(con, nombre: str, n: int = 60) -> dict | None:
    sorteos = db.cargar(con, nombre)
    if not sorteos:
        return None
    frec = Counter(num for s in sorteos for num in s.numeros)
    salida = {
        "nombre": nombre,
        "grupo": sorteos[-1].grupo,
        "total": len(sorteos),
        "desde": sorteos[0].fecha.isoformat(),
        "sorteos": [{"fecha": s.fecha.isoformat(), "numeros": list(s.numeros)}
                    for s in reversed(sorteos[-n:])],
        "mas_salidos": frec.most_common(10),
        "atrasados": [],
    }
    # "Atrasados" solo tiene sentido en juegos de números 00-99 (quinielas, palés...)
    if all(len(num) == 2 for s in sorteos for num in s.numeros):
        sin_salir = {f"{i:02d}": len(sorteos) for i in range(100)}
        for pos, s in enumerate(reversed(sorteos)):
            for num in s.numeros:
                sin_salir[num] = min(sin_salir[num], pos)
        salida["atrasados"] = sorted(sin_salir.items(), key=lambda x: (-x[1], x[0]))[:10]
    return salida


# --------------------------------------------------------- recomendaciones

DIAS_PRUEBA = 60      # días con los que el Oráculo aprende y se mide
DIAS_INACTIVA = 7     # loterías sin sorteos en tantos días no se recomiendan
DESTACADOS = 8

_cache_sim: dict = {}


def _simulacion(todos: list[db.Sorteo], fecha: date) -> motor.Simulacion:
    """El Oráculo entrenado con los DIAS_PRUEBA anteriores a `fecha` (se guarda en memoria)."""
    clave = (fecha, len(todos))
    if clave not in _cache_sim:
        previos = [s for s in todos if s.fecha < fecha]
        _cache_sim.clear()
        _cache_sim[clave] = motor.simular(previos, REGLAS, fecha - timedelta(days=DIAS_PRUEBA))
    return _cache_sim[clave]


def _stats(r: motor.Resultado) -> dict:
    return {
        "jugadas": r.jugadas, "numeros": r.numeros_jugados, "aciertos": r.aciertos,
        "con_acierto": r.jugadas_con_acierto, "esperado": round(r.esperado_azar, 2),
        "tasa": round(r.tasa, 4),
        "vs_azar": round(r.vs_azar, 3), "z": round(r.z, 2),
    }


def recomendaciones(con, fecha: date, solo: str | None = None) -> dict | None:
    todos = db.cargar(con)
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()

    ultimos: dict[str, db.Sorteo] = {}   # último sorteo de cada lotería antes de `fecha`
    reales: dict[str, db.Sorteo] = {}    # resultado de ese día, si ya salió
    for s in todos:
        if s.fecha < fecha:
            ultimos[s.loteria] = s
        elif s.fecha == fecha:
            reales[s.loteria] = s

    señales: dict[str, dict[str, list[str]]] = defaultdict(dict)  # lotería -> regla -> números
    for p in motor.predecir(todos, REGLAS, fecha):
        if (solo and p.loteria != solo) or (fecha - ultimos[p.loteria].fecha).days > DIAS_INACTIVA:
            continue
        señales[p.loteria][p.regla] = p.numeros

    sim = _simulacion(todos, fecha)
    filas, candidatas = [], []
    jugados = aciertos = 0
    for lot, preds in señales.items():
        real = reales.get(lot)
        salidos = set(real.numeros) if real else None
        acierto = (lambda n: None) if salidos is None else (lambda n: n in salidos)
        jugadas = [{"numero": j.numero, "fuerza": round(j.fuerza, 3), "reglas": j.reglas,
                    "acierto": acierto(j.numero)} for j in motor.oraculo(preds, sim.pesos)]
        if salidos is not None:
            jugados += len(jugadas)
            aciertos += sum(x["acierto"] for x in jugadas)
        u = ultimos[lot]
        filas.append((u.grupo, {
            "nombre": lot,
            "oraculo": jugadas,
            "senales": [{"regla": r, "numeros": [{"numero": n, "acierto": acierto(n)} for n in nums]}
                        for r, nums in sorted(preds.items(), key=lambda x: -sim.pesos.get(x[0], 1))],
            "resultado": list(real.numeros) if real else None,
            "ultimo": {"fecha": u.fecha.isoformat(), "numeros": list(u.numeros)},
        }))
        candidatas += [{"loteria": lot, "grupo": u.grupo, **x} for x in jugadas]

    # Primero las que todavía se pueden jugar, luego las de más fuerza
    destacados = sorted(candidatas, key=lambda x: (x["acierto"] is not None, -x["fuerza"], -len(x["reglas"])))
    primero, tope = todos[0].fecha, max(hoy, todos[-1].fecha) + timedelta(days=1)
    descripciones = {r.nombre: r.descripcion for r in REGLAS}
    oraculo = sim.resultados[motor.ORACULO]
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primero else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha + timedelta(days=1) <= tope else None,
        "total_reglas": len(REGLAS),
        "resumen": {
            "loterias": len(filas),
            "sorteadas": sum(1 for _, f in filas if f["resultado"]),
            "jugados": jugados,
            "aciertos": aciertos,
            "esperado": round(jugados * motor.PROB_AZAR, 2),
        },
        "destacados": destacados[:DESTACADOS],
        "grupos": _agrupar(filas),
        "oraculo": {
            **_stats(oraculo),
            "serie": [{"fecha": f.isoformat(), "aciertos": a, "esperado": round(e, 3)}
                      for f, a, e in sim.serie],
        },
        "reglas": sorted(({"nombre": nombre, "descripcion": descripciones.get(nombre, ""),
                           "peso": round(sim.pesos.get(nombre, 1), 3), **_stats(r)}
                          for nombre, r in sim.resultados.items() if nombre != motor.ORACULO),
                         key=lambda r: -r["peso"]),
        "dias_prueba": DIAS_PRUEBA,
        "prob_azar": round(motor.PROB_AZAR, 4),
    }


# ---------------------------------------------------------- loterías indicadas

_cache_libro: dict = {}


def _prueba_libro(todos: list[db.Sorteo], fecha: date) -> motor.Simulacion:
    """Cómo le fue al método de los libros en los DIAS_PRUEBA anteriores a `fecha`."""
    clave = (fecha, len(todos))
    if clave not in _cache_libro:
        previos = [s for s in todos if s.fecha < fecha]
        _cache_libro.clear()
        _cache_libro[clave] = motor.simular(previos, libro.REGLAS, fecha - timedelta(days=DIAS_PRUEBA),
                                            libro.NOMBRES)
    return _cache_libro[clave]


def _prueba_primero(todos: list[db.Sorteo], fecha: date) -> dict:
    """Cuántas veces el número principal (y los 3 candidatos) acertó el 1er premio
    en los DIAS_PRUEBA anteriores a `fecha`, sin ver el resultado antes de jugar."""
    clave = ("primero", fecha, len(todos))
    if clave not in _cache_libro:
        desde = fecha - timedelta(days=DIAS_PRUEBA)
        historial: dict[str, list[db.Sorteo]] = defaultdict(list)
        sorteos = principal = en_tres = 0
        for s in todos:
            if s.fecha >= fecha:
                break
            if s.loteria not in libro.NOMBRES:
                continue
            h = historial[s.loteria]
            if h and s.fecha >= desde:
                candidatos = [j.numero for j in
                              libro.primer_premio(Contexto(s.loteria, s.fecha, h, [])).jugadas[:libro.JUGADAS]]
                sorteos += 1
                principal += candidatos[0] == s.numeros[0]
                en_tres += s.numeros[0] in candidatos
            h.append(s)
        p = libro.PROB_PRIMERO

        def medir(aciertos: int, jugados: int, prob: float) -> dict:
            esperado = jugados * prob
            var = jugados * prob * (1 - prob)
            return {"aciertos": aciertos, "esperado": round(esperado, 2),
                    "vs_azar": round(aciertos / esperado, 3) if esperado else 0,
                    "z": round((aciertos - esperado) / var ** .5, 2) if var else 0}

        _cache_libro[clave] = {"sorteos": sorteos, "principal": medir(principal, sorteos, p),
                               "tres": medir(en_tres, sorteos, libro.JUGADAS * p)}
    return _cache_libro[clave]


def _salio(salidos: set[str] | None, numeros) -> bool | None:
    """None si el sorteo no ha salido; si no, si salieron todos los números."""
    return None if salidos is None else all(n in salidos for n in numeros)


def indicadas(con, fecha: date) -> dict | None:
    todos = db.cargar(con)
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    previos = [s for s in todos if s.fecha < fecha]
    historial: dict[str, list[db.Sorteo]] = defaultdict(list)
    reales: dict[str, db.Sorteo] = {}
    for s in todos:
        if s.loteria in libro.NOMBRES:
            if s.fecha < fecha:
                historial[s.loteria].append(s)
            elif s.fecha == fecha:
                reales[s.loteria] = s

    tarjetas = []
    jugados = aciertos = 0
    for etiqueta, nombre in libro.INDICADAS:
        h = historial.get(nombre)
        if not h or (fecha - h[-1].fecha).days > DIAS_INACTIVA:
            continue
        ctx = Contexto(nombre, fecha, h, previos)
        a = libro.analizar(ctx)
        pp = libro.primer_premio(ctx)
        real = reales.get(nombre)
        salidos = set(real.numeros) if real else None
        elegidos = [j.numero for j in a.jugadas[:libro.JUGADAS]]
        jugadas = [{"numero": j.numero, "votos": j.votos, "fuentes": j.fuentes,
                    "acierto": _salio(salidos, [j.numero])} for j in a.jugadas[:libro.JUGADAS]]
        if salidos is not None:
            jugados += len(jugadas)
            aciertos += sum(x["acierto"] for x in jugadas)
        tarjetas.append({
            "etiqueta": etiqueta,
            "nombre": nombre,
            "jugadas": jugadas,
            "pale": {"numeros": elegidos[:2], "acierto": _salio(salidos, elegidos[:2])},
            "tripleta": {"numeros": elegidos, "acierto": _salio(salidos, elegidos)},
            "fuentes": [{"fuente": f, "numeros": [{"numero": n, "acierto": _salio(salidos, [n])} for n in nums]}
                        for f, nums in a.fuentes.items()],
            "secuencias": [{"texto": s.texto, "nota": s.nota,
                            "pales": [{"numeros": p.split("-"), "acierto": _salio(salidos, p.split("-"))}
                                      for p in s.pales]} for s in a.secuencias],
            "primero": [{"numero": j.numero, "votos": j.votos, "fuentes": j.fuentes,
                         "acierto": None if real is None else j.numero == real.numeros[0]}
                        for j in pp.jugadas[:libro.JUGADAS]],
            "resultado": list(real.numeros) if real else None,
            "ultimo": {"fecha": h[-1].fecha.isoformat(), "numeros": list(h[-1].numeros)},
        })

    sim = _prueba_libro(todos, fecha)
    primero, tope = todos[0].fecha, max(hoy, todos[-1].fecha) + timedelta(days=1)
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primero else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha + timedelta(days=1) <= tope else None,
        "dia": libro.POR_DIA[fecha.weekday()],
        "del_mes": libro.POR_FECHA[fecha.day],
        "resumen": {
            "loterias": len(tarjetas),
            "sorteadas": sum(1 for t in tarjetas if t["resultado"]),
            "jugados": jugados,
            "aciertos": aciertos,
            "esperado": round(jugados * motor.PROB_AZAR, 2),
        },
        "loterias": tarjetas,
        "prueba": [{"nombre": r.nombre, "descripcion": r.descripcion, **_stats(sim.resultados[r.nombre])}
                   for r in libro.REGLAS],
        "prueba_primero": _prueba_primero(todos, fecha),
        "prob_primero": libro.PROB_PRIMERO,
        "dias_prueba": DIAS_PRUEBA,
    }


# ------------------------------------------------------------ los 7 más fuertes

AÑOS_FUERTES = 3
CUANTOS_FUERTES = 7
# Las indicadas y, además, estas (como se muestra, nombre en la base de datos)
LOTERIAS_FUERTES = libro.INDICADAS + [
    ("Real Noche", "Lotería Real Noche"),
    ("Loteka Día", "Quiniela Loteka Día"), ("Loteka Noche", "Quiniela Loteka Noche"),
    ("King Lottery Día", "King Lottery Día"), ("King Lottery Noche", "King Lottery Noche"),
    ("Florida Día", "Florida Día"), ("Florida Noche", "Florida Noche"),
]
NOMBRES_FUERTES = [n for _, n in LOTERIAS_FUERTES]


def _top(veces: Counter, ultima: dict[str, date], master: list[str]) -> list[tuple[str, str]]:
    """Las parejas número-inverso más salidas (23 cuenta junto con 32), como (principal, inverso).

    La fuerza de la pareja es la suma de los dos; en empate van primero las que tienen algún
    número en la fila Master y luego la que salió más recientemente. El principal es el
    que más salió de los dos. En 11, 22, 33... el inverso es el mismo número.
    """
    nunca = date.min
    parejas = {min(n, n[::-1]) for n in veces}
    def fuerza(k):
        return veces[k] + (veces[k[::-1]] if k != k[::-1] else 0)
    def reciente(k):
        return max(ultima.get(k, nunca), ultima.get(k[::-1], nunca))
    elegidas = sorted(parejas, key=lambda k: (-fuerza(k), k not in master and k[::-1] not in master,
                                              -reciente(k).toordinal(), k))[:CUANTOS_FUERTES]
    salida = []
    for k in elegidas:
        a, b = k, k[::-1]
        if (veces[b], ultima.get(b, nunca)) > (veces[a], ultima.get(a, nunca)):
            a, b = b, a
        salida.append((a, b))
    return salida


@dataclass
class _Recorrido:
    ventana: dict[str, list[db.Sorteo]]     # sorteos de los últimos AÑOS_FUERTES años, por lotería
    veces: dict[str, Counter]
    primero: dict[str, Counter]             # veces de 1er premio
    ultima: dict[str, dict[str, date]]      # última vez que salió cada número
    reales: dict[str, db.Sorteo]            # resultado del día, si ya salió
    prueba: dict


def _recorrer(todos: list[db.Sorteo], fecha: date, elegir) -> _Recorrido:
    """Recorre los sorteos en orden contando los últimos AÑOS_FUERTES años de cada lotería.

    Antes de cada sorteo de los DIAS_PRUEBA anteriores a `fecha` juega los números que da
    `elegir(sorteo, ventana, veces, ultima)` con lo que había hasta ese momento, así la
    prueba nunca ve el resultado que juega. El resultado de `fecha` no se cuenta.
    """
    prueba_desde = fecha - timedelta(days=DIAS_PRUEBA)
    r = _Recorrido(defaultdict(list), defaultdict(Counter), defaultdict(Counter), defaultdict(dict), {}, {})
    sorteos = jugados = aciertos = con_acierto = 0
    for s in todos:
        if s.fecha == fecha:
            r.reales[s.loteria] = s
            continue
        v = r.ventana[s.loteria]
        while v and v[0].fecha < s.fecha - timedelta(days=365 * AÑOS_FUERTES):
            viejo = v.pop(0)
            r.veces[s.loteria].subtract(viejo.numeros)
            r.primero[s.loteria][viejo.numeros[0]] -= 1
        if s.fecha >= prueba_desde and len(v) >= 30:
            elegidos = elegir(s, v, +r.veces[s.loteria], r.ultima[s.loteria])
            sorteos += 1
            jugados += len(elegidos)
            ac = len(elegidos & set(s.numeros))
            aciertos += ac
            con_acierto += ac > 0
        v.append(s)
        r.veces[s.loteria].update(s.numeros)
        r.primero[s.loteria][s.numeros[0]] += 1
        for n in s.numeros:
            r.ultima[s.loteria][n] = s.fecha

    esperado = jugados * motor.PROB_AZAR
    var = jugados * motor.PROB_AZAR * (1 - motor.PROB_AZAR)
    r.prueba = {
        "sorteos": sorteos, "jugados": jugados, "aciertos": aciertos, "con_acierto": con_acierto,
        "esperado": round(esperado, 1),
        "vs_azar": round(aciertos / esperado, 3) if esperado else 0,
        "z": round((aciertos - esperado) / var ** .5, 2) if var else 0,
        "prob_alguno": round(1 - (1 - motor.PROB_AZAR) ** (jugados / sorteos), 4) if sorteos else 0,
    }
    return r


def fuertes(con, fecha: date) -> dict | None:
    todos = [s for s in db.cargar(con, hasta=fecha) if s.loteria in NOMBRES_FUERTES]
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    desde = fecha - timedelta(days=365 * AÑOS_FUERTES)
    r = _recorrer(todos, fecha, lambda s, v, veces, ultima: {
        n for par in _top(veces, ultima, libro_master.LIBRO[v[-1].numeros[0]]) for n in par})
    ventana, veces, primero, ultima, reales = r.ventana, r.veces, r.primero, r.ultima, r.reales

    tarjetas = []
    for etiqueta, nombre in LOTERIAS_FUERTES:
        v = [x for x in ventana.get(nombre, []) if x.fecha >= desde]
        if not v:
            continue
        real = reales.get(nombre)
        salidos = set(real.numeros) if real else None
        cuenta = +veces[nombre]
        fila = libro_master.LIBRO[v[-1].numeros[0]]
        esperado = len(v) * motor.PROB_AZAR
        tarjetas.append({
            "etiqueta": etiqueta,
            "nombre": nombre,
            "sorteos": len(v),
            "desde": v[0].fecha.isoformat(),
            "esperado": round(esperado, 1),
            # Número e inverso cuentan como uno solo: todas las cifras son de la pareja
            "numeros": [{"numero": n, "inverso": inv if inv != n else None,
                         "veces": sum(cuenta[x] for x in {n, inv}),
                         "primero": sum(primero[nombre][x] for x in {n, inv}),
                         # Fuerza: % de sorteos en que la pareja salió de 1er premio (lo normal: 1 % por número)
                         "fuerza_primera": round(sum(primero[nombre][x] for x in {n, inv}) / len(v), 4),
                         "normal_primera": 0.01 * len({n, inv}),
                         "detalle": [cuenta[n], cuenta[inv]] if inv != n else [cuenta[n]],
                         "vs_azar": round(sum(cuenta[x] for x in {n, inv}) / (esperado * len({n, inv})), 2),
                         "hace": min((fecha - ultima[nombre][x]).days for x in (n, inv) if x in ultima[nombre]),
                         "master": n in fila or inv in fila,
                         "acierto": _salio(salidos, [n]),
                         "acierto_inverso": _salio(salidos, [inv]) if inv != n else None}
                        for n, inv in _top(cuenta, ultima[nombre], fila)],
            "master": {"numero": v[-1].numeros[0], "fila": fila},
            "resultado": list(real.numeros) if real else None,
        })

    primer_dia = todos[0].fecha
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primer_dia else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "años": AÑOS_FUERTES,
        "cuantos": CUANTOS_FUERTES,
        "desde": max(desde, primer_dia).isoformat(),
        "completo": primer_dia <= desde,
        "loterias": tarjetas,
        "prueba": r.prueba,
        "dias_prueba": DIAS_PRUEBA,
    }


# --------------------------------------------------------------- Master King

def master_king(con, fecha: date) -> dict | None:
    """Capítulos 05 y 07: los números del último sorteo de cada lotería abren sus filas y
    se juegan los libro_king.CUANTOS de esas filas que más han salido en esa lotería."""
    todos = [s for s in db.cargar(con, hasta=fecha) if s.loteria in NOMBRES_FUERTES]
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    desde = fecha - timedelta(days=365 * AÑOS_FUERTES)
    r = _recorrer(todos, fecha, lambda s, v, veces, ultima: {
        x["numero"] for x in libro_king.jugar(v[-1].numeros, veces, ultima)})

    tarjetas = []
    for etiqueta, nombre in LOTERIAS_FUERTES:
        v = [x for x in r.ventana.get(nombre, []) if x.fecha >= desde]
        if not v:
            continue
        real = r.reales.get(nombre)
        salidos = set(real.numeros) if real else None
        cuenta, ultima = +r.veces[nombre], r.ultima[nombre]
        abre = v[-1]
        tarjetas.append({
            "etiqueta": etiqueta,
            "nombre": nombre,
            "sorteos": len(v),
            "abre": {"fecha": abre.fecha.isoformat(), "numeros": list(abre.numeros),
                     "filas": [{"primero": p, "siguen": libro_king.LIBRO[p]}
                               for p in dict.fromkeys(abre.numeros) if p in libro_king.LIBRO]},
            "numeros": [{**x, "hace": (fecha - ultima[x["numero"]]).days if x["numero"] in ultima else None,
                         "acierto": _salio(salidos, [x["numero"]])}
                        for x in libro_king.jugar(abre.numeros, cuenta, ultima)],
            "resultado": list(real.numeros) if real else None,
        })

    primer_dia = todos[0].fecha
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primer_dia else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "cuantos": libro_king.CUANTOS,
        "años": AÑOS_FUERTES,
        "desde": max(desde, primer_dia).isoformat(),
        "loterias": tarjetas,
        "prueba": r.prueba,
        "dias_prueba": DIAS_PRUEBA,
    }


# ------------------------------------------------------------------ 3 en raya

# 3 en raya no mira La Primera, New York ni Florida
_FUERA_RAYA = {"La Primera Día", "Primera Noche", "New York Tarde", "New York Noche", "Florida Día", "Florida Noche"}
LOTERIAS_RAYA = [(e, n) for e, n in LOTERIAS_FUERTES if n not in _FUERA_RAYA]
NOMBRES_RAYA = [n for _, n in LOTERIAS_RAYA]

def _raya(todos: list[db.Sorteo], dia: date) -> tuple[dict[str, list[db.Sorteo]], Counter, list[dict]]:
    """La jugada de 3 en raya para `dia`, con los sorteos de los AÑOS_FUERTES años anteriores."""
    desde = dia - timedelta(days=365 * AÑOS_FUERTES)
    historiales: dict[str, list[db.Sorteo]] = defaultdict(list)
    for s in todos:
        if desde <= s.fecha < dia:
            historiales[s.loteria].append(s)
    historiales = {n: h for n, h in historiales.items() if (dia - h[-1].fecha).days <= DIAS_INACTIVA}
    veces = Counter(n for h in historiales.values() for s in h for n in s.numeros)
    return historiales, veces, libro_raya.jugar(historiales, veces)


def tres_en_raya(con, fecha: date) -> dict | None:
    todos = [s for s in db.cargar(con, hasta=fecha) if s.loteria in NOMBRES_RAYA]
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    historiales, veces, jugada = _raya(todos, fecha)
    reales = {s.loteria: s for s in todos if s.fecha == fecha}
    salidos = {n for s in reales.values() for n in s.numeros}

    ultima: dict[str, date] = {}
    for h in historiales.values():
        for s in h:
            for n in s.numeros:
                ultima[n] = max(ultima.get(n, s.fecha), s.fecha)
    numeros = []
    for x in jugada:
        n, inv = x["numero"], x["inverso"]
        vistos = [(fecha - ultima[y]).days for y in (n, inv) if y in ultima]
        numeros.append({**x, "inverso": inv if inv != n else None,
                        "hace": min(vistos) if vistos else None,
                        "donde": [s.loteria for s in reales.values() if {n, inv} & set(s.numeros)]})
    elegidos = {y for x in jugada for y in (x["numero"], x["inverso"])}

    abiertos, resultados = [], []
    for etiqueta, nombre in LOTERIAS_RAYA:
        h = historiales.get(nombre)
        if h:
            abiertos.append({"etiqueta": etiqueta, "nombre": nombre, "fecha": h[-1].fecha.isoformat(),
                             "numeros": list(h[-1].numeros),
                             "campos": [{"primero": p, "siguen": libro_raya.LIBRO[p]}
                                        for p in h[-1].numeros if p in libro_raya.LIBRO]})
        if nombre in reales:
            resultados.append({"etiqueta": etiqueta, "nombre": nombre, "numeros": list(reales[nombre].numeros),
                               "aciertos": len(elegidos & set(reales[nombre].numeros))})

    # Cómo le fue: cada uno de los DIAS_PRUEBA días anteriores, con lo que había hasta ese día
    clave = (fecha, len(todos))
    if clave not in _cache_raya:
        sorteos = jugados = aciertos = con_acierto = 0
        por_dia: dict[date, list[db.Sorteo]] = defaultdict(list)
        for s in todos:
            if fecha - timedelta(days=DIAS_PRUEBA) <= s.fecha < fecha:
                por_dia[s.fecha].append(s)
        for dia, del_dia in sorted(por_dia.items()):
            jugar = {y for x in _raya(todos, dia)[2] for y in (x["numero"], x["inverso"])}
            for s in del_dia:
                ac = len(jugar & set(s.numeros))
                sorteos, jugados, aciertos, con_acierto = sorteos + 1, jugados + len(jugar), aciertos + ac, con_acierto + (ac > 0)
        p = motor.PROB_AZAR
        _cache_raya[clave] = {**_medir(aciertos, jugados, p), "sorteos": sorteos, "con_acierto": con_acierto,
                              "prob_alguno": round(1 - (1 - p) ** (jugados / sorteos), 4) if sorteos else 0}

    primer_dia = todos[0].fecha
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primer_dia else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "cuantos": libro_raya.CUANTOS,
        "años": AÑOS_FUERTES,
        "numeros": numeros,
        "abiertos": abiertos,
        "resultados": resultados,
        "sorteadas": len(resultados),
        "total": len(historiales),
        "prueba": _cache_raya[clave],
        "dias_prueba": DIAS_PRUEBA,
    }


_cache_raya: dict = {}

# ------------------------------------------------------------------- Josefina

NOMBRES_JOSEFINA = [n for nombres in libro_josefina.FAMILIAS.values() for n in nombres]


def josefina(con, fecha: date) -> dict | None:
    """Guía Josefina: en cada lotería, lo que salió ayer (y anteayer) en sus loterías indicadas
    abre sus secuencias, y se juegan los libro_josefina.CUANTOS números más respaldados con su V."""
    todos = [s for s in db.cargar(con, hasta=fecha) if s.loteria in NOMBRES_JOSEFINA]
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    indice = {(s.loteria, s.fecha): s for s in todos}
    buscar = lambda loteria, dia: indice.get((loteria, dia))  # noqa: E731
    ultimo = {s.loteria: s.fecha for s in todos if s.fecha < fecha}

    tarjetas = []
    for familia, nombres in libro_josefina.FAMILIAS.items():
        for nombre in nombres:
            if nombre not in ultimo or (fecha - ultimo[nombre]).days > DIAS_INACTIVA:
                continue
            real = indice.get((nombre, fecha))
            salidos = set(real.numeros) if real else None
            j = libro_josefina.jugar(nombre, fecha, buscar)
            tarjetas.append({
                "nombre": nombre,
                "familia": familia,
                "fuerte": familia in libro_josefina.MAS_FUERTES,
                "indicadas": [f for f, _ in libro_josefina.de_donde(familia)],
                "numeros": [{**x, "acierto": _salio(salidos, [x["numero"]]),
                             "acierto_v": _salio(salidos, [x["inverso"]]) if x["inverso"] else None}
                            for x in j["jugada"]],
                "abiertas": j["abiertas"],
                "pales": j["pales"],
                "resultado": list(real.numeros) if real else None,
            })

    # Cómo le fue: cada sorteo de los DIAS_PRUEBA días anteriores, con lo que había antes de ese día
    clave = (fecha, len(todos))
    if clave not in _cache_josefina:
        sorteos = jugados = aciertos = con_acierto = con_v = 0
        for s in todos:
            if fecha - timedelta(days=DIAS_PRUEBA) <= s.fecha < fecha:
                j = libro_josefina.jugar(s.loteria, s.fecha, buscar)["jugada"]
                if not j:
                    continue
                directos = {x["numero"] for x in j}
                ac = len(directos & set(s.numeros))
                sorteos, jugados, aciertos = sorteos + 1, jugados + len(directos), aciertos + ac
                con_acierto += ac > 0
                con_v += any(x["inverso"] in s.numeros for x in j if x["inverso"])
        p = motor.PROB_AZAR
        _cache_josefina[clave] = {**_medir(aciertos, jugados, p), "sorteos": sorteos, "con_acierto": con_acierto,
                                  "con_v": con_v,
                                  "prob_alguno": round(1 - (1 - p) ** (jugados / sorteos), 4) if sorteos else 0}

    primer_dia = todos[0].fecha
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primer_dia else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "cuantos": libro_josefina.CUANTOS,
        "indica": libro_josefina.INDICA,
        "loterias": tarjetas,
        "prueba": _cache_josefina[clave],
        "dias_prueba": DIAS_PRUEBA,
    }


_cache_josefina: dict = {}

# ------------------------------------------------------------- Público y VIP

# Los 7 más fuertes en 1ra, contando estas loterías juntas como si fueran una sola
LOTERIAS_VIP = [
    ("Nacional", "Lotería Nacional"), ("Gana Más", "Gana Más"),
    ("Primera", "La Primera Día"), ("Primera", "Primera Noche"),
    ("Nueva York", "New York Tarde"), ("Nueva York", "New York Noche"),
    ("Suerte", "La Suerte 12:30"), ("Suerte", "La Suerte 18:00"),
    ("Real", "Quiniela Real"), ("Loteka", "Quiniela Loteka Noche"),
]
NOMBRES_VIP = [n for _, n in LOTERIAS_VIP]
CUANTOS_PUBLICO = 4  # los de más fuerza en 1ra; los otros 3 de los 7 son VIP
# El Libro oculto mira los 1ros premios de estas (el libro dice que va mejor en Nacional, Florida y New York)
NOMBRES_OCULTO = NOMBRES_VIP + ["Florida Día", "Florida Noche"]
VIDA_PRIMERA = 7     # días: un 1er premio de hace 7 días vale la mitad que uno de ayer


def _vip(todos: list[db.Sorteo], dia: date) -> tuple[list[db.Sorteo], list[dict]]:
    """Las 7 parejas número-inverso más fuertes en 1er premio para `dia`, con los sorteos de los
    AÑOS_FUERTES años anteriores de todas las loterías juntas (los CUANTOS_PUBLICO primeros son
    del Público).

    Cada vez que la pareja salió de 1er premio suma un punto que se va gastando con el tiempo
    (a los VIDA_PRIMERA días vale la mitad). Su probabilidad en 1ra es esa suma entre la de todos
    los sorteos: lo que pasaría si el reciente pesa más. En empate, la que más ha salido en total.
    """
    desde = dia - timedelta(days=365 * AÑOS_FUERTES)
    historiales: dict[str, list[db.Sorteo]] = defaultdict(list)
    for s in todos:
        if desde <= s.fecha < dia:
            historiales[s.loteria].append(s)
    sorteos = [s for h in historiales.values() if (dia - h[-1].fecha).days <= DIAS_INACTIVA for s in h]
    if not sorteos:
        return sorteos, []
    veces = Counter(n for s in sorteos for n in s.numeros)
    primero, peso = Counter(), Counter()
    reciente = Counter()  # 1ros premios en los últimos VIDA_PRIMERA días
    ultima: dict[str, date] = {}
    ultima_1ra: dict[str, date] = {}
    total = 0.0
    for s in sorteos:
        w = 0.5 ** ((dia - s.fecha).days / VIDA_PRIMERA)
        total += w
        n = s.numeros[0]
        primero[n] += 1
        peso[n] += w
        reciente[n] += (dia - s.fecha).days <= VIDA_PRIMERA
        ultima_1ra[n] = max(ultima_1ra.get(n, s.fecha), s.fecha)
        for x in s.numeros:
            ultima[x] = max(ultima.get(x, s.fecha), s.fecha)

    def par(k):
        return {k, k[::-1]}
    fuerza = {k: sum(peso[x] for x in par(k)) for k in {min(n, n[::-1]) for n in peso}}
    elegidas = sorted(fuerza, key=lambda k: (-fuerza[k], -sum(veces[x] for x in par(k)), k))[:CUANTOS_FUERTES]
    parejas = []
    for k in elegidas:
        n, inv = k, k[::-1]
        if (peso[inv], veces[inv]) > (peso[n], veces[n]):  # la bola grande: la que más pesa en 1ra
            n, inv = inv, n
        p = par(k)
        parejas.append({"numero": n, "inverso": inv, "veces": sum(veces[x] for x in p),
                        "detalle": [primero[n], primero[inv]] if inv != n else [primero[n]],
                        "primero": sum(primero[x] for x in p),
                        "reciente": sum(reciente[x] for x in p),
                        "probabilidad": round(fuerza[k] / total, 4),
                        "normal": 0.01 * len(p),
                        "hace": min((dia - ultima[x]).days for x in p if x in ultima),
                        "hace_1ra": min((dia - ultima_1ra[x]).days for x in p if x in ultima_1ra)})
    return sorteos, parejas


def publico_vip(con, fecha: date) -> dict | None:
    # solo se predice el día que sigue al último resultado; más allá serían los mismos números
    ultimo = con.execute(f"SELECT MAX(fecha) FROM sorteos WHERE loteria IN ({','.join('?' * len(NOMBRES_VIP))})",
                         NOMBRES_VIP).fetchone()[0]
    if ultimo is None:
        return None
    hoy = min(datetime.now(recolector.ZONA_RD).date(), date.fromisoformat(ultimo) + timedelta(days=1))
    fecha = min(fecha, hoy)
    cargados = db.cargar(con, hasta=fecha)
    todos = [s for s in cargados if s.loteria in NOMBRES_VIP]
    if not todos:
        return None
    sorteos, parejas = _vip(todos, fecha)
    # Libro oculto: lo que abren los 1ros premios de los últimos días; si coincide con el Público o
    # el VIP, ese número cumple los dos métodos (fuego)
    abiertos, abiertas = libro_oculto.abiertos(
        libro_oculto.primeras_de([s for s in cargados if s.loteria in NOMBRES_OCULTO], fecha))
    reales = {s.loteria: s for s in todos if s.fecha == fecha}

    def jugados(lista):
        return {y for x in lista for y in (x["numero"], x["inverso"])}
    publico, vip = jugados(parejas[:CUANTOS_PUBLICO]), jugados(parejas[CUANTOS_PUBLICO:])
    numeros = []
    for x in parejas:
        p = {x["numero"], x["inverso"]}
        numeros.append({**x, "inverso": x["inverso"] if x["inverso"] != x["numero"] else None,
                        "fuego": [y for y in (x["numero"], x["inverso"]) if y in abiertos],
                        "oculto": {y: abiertos[y] for y in dict.fromkeys((x["numero"], x["inverso"])) if y in abiertos},
                        "en_primera": [s.loteria for s in reales.values() if s.numeros[0] in p],
                        "donde": [s.loteria for s in reales.values() if p & set(s.numeros)]})
    resultados = []
    for e, n in LOTERIAS_VIP:
        if n in reales:
            nums = reales[n].numeros
            resultados.append({"etiqueta": e, "nombre": n, "numeros": list(nums),
                               "primera": "publico" if nums[0] in publico else "vip" if nums[0] in vip else None,
                               "publico": len(publico & set(nums)), "vip": len(vip & set(nums))})

    # Cómo le fue: cada uno de los DIAS_PRUEBA días anteriores, con lo que había hasta ese día
    clave = (fecha, len(todos))
    if clave not in _cache_vip:
        por_dia: dict[date, list[db.Sorteo]] = defaultdict(list)
        for s in todos:
            if fecha - timedelta(days=DIAS_PRUEBA) <= s.fecha < fecha:
                por_dia[s.fecha].append(s)
        # [aciertos en 1ra, aciertos en cualquier premio, números jugados, sorteos con acierto]
        cuenta = {"publico": [0, 0, 0, 0], "vip": [0, 0, 0, 0]}
        total = 0
        for dia, del_dia in sorted(por_dia.items()):
            p = _vip(todos, dia)[1]
            if not p:
                continue
            for parte, lista in (("publico", p[:CUANTOS_PUBLICO]), ("vip", p[CUANTOS_PUBLICO:])):
                jugar = jugados(lista)
                c = cuenta[parte]
                for s in del_dia:
                    ac = len(jugar & set(s.numeros))
                    c[0] += s.numeros[0] in jugar
                    c[1], c[2], c[3] = c[1] + ac, c[2] + len(jugar), c[3] + (ac > 0)
            total += len(del_dia)
        prob = motor.PROB_AZAR
        _cache_vip.clear()
        _cache_vip[clave] = {"sorteos": total, **{
            parte: {**_medir(a, j, prob), "con_acierto": ca,
                    "prob_alguno": round(1 - (1 - prob) ** (j / total), 4) if total else 0,
                    # en 1ra: cada número jugado tiene 1 % de ser el 1er premio
                    "primera": _medir(a1, j, libro.PROB_PRIMERO)}
            for parte, (a1, a, j, ca) in cuenta.items()}}

    primer_dia = todos[0].fecha
    desde = fecha - timedelta(days=365 * AÑOS_FUERTES)
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primer_dia else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "años": AÑOS_FUERTES,
        "cuantos": CUANTOS_FUERTES,
        "cuantos_publico": CUANTOS_PUBLICO,
        "vida_primera": VIDA_PRIMERA,
        "desde": max(desde, primer_dia).isoformat(),
        "completo": primer_dia <= desde,
        "sorteos": len(sorteos),
        "loterias": [{"etiqueta": e, "nombre": n} for e, n in LOTERIAS_VIP],
        "publico": numeros[:CUANTOS_PUBLICO],
        "vip": numeros[CUANTOS_PUBLICO:],
        "resultados": resultados,
        "prueba": _cache_vip[clave],
        "dias_prueba": DIAS_PRUEBA,
        "oculto": {"dias": libro_oculto.DIAS_ATRAS, "loterias": NOMBRES_OCULTO, "abiertas": abiertas,
                   "fuego": sorted({y for x in numeros for y in x["fuego"]})},
    }


_cache_vip: dict = {}

# --------------------------------------------------------------- Laboratorio

# Un número sale en un sorteo en 1ra con 1 % y en cualquier premio con ≈ 2.97 %
CUANTOS_CONSENSO = 7
Z_AZAR = 2.0  # entre −2 y +2 es suerte normal


def _numeros_de(nombre: str, r: dict) -> set[str]:
    """Los números que recomienda cada método ese día (en cualquiera de sus loterías)."""
    def par(x):
        return {x["numero"], x["inverso"]} - {None}
    if nombre == "El Oráculo":
        return {x["numero"] for x in r["destacados"]}
    if nombre == "Loterías indicadas":
        return {j["numero"] for l in r["loterias"] for j in l["jugadas"]}
    if nombre == "Los 7 más fuertes":
        return {n for l in r["loterias"] for x in l["numeros"] for n in par(x)}
    if nombre == "Master":
        return {x["numero"] for l in r["loterias"] for x in l["ranking"]}
    if nombre == "Master King":
        return {x["numero"] for l in r["loterias"] for x in l["numeros"]}
    if nombre == "3 en raya":
        return {n for x in r["numeros"] for n in par(x)}
    if nombre == "Josefina":
        return {n for l in r["loterias"] for x in l["numeros"] for n in par(x)}
    if nombre == "Público y VIP":
        return {n for x in r["publico"] + r["vip"] for n in par(x)}
    if nombre == "La Fórmula":
        return {x["numero"] for x in r["origen"]["formula"]}
    return set()


def _verdad(nombre: str, que: str, m: dict, enlace: str) -> dict:
    return {"metodo": nombre, "mide": que, "aciertos": m["aciertos"], "esperado": m["esperado"],
            "vs_azar": m["vs_azar"], "z": m["z"], "enlace": enlace}


def _prueba_fuego(con, fecha: date) -> dict:
    """1ros premios de los números con fuego del Público y VIP en los DIAS_PRUEBA días anteriores."""
    cargados = db.cargar(con, hasta=fecha)
    vip = [s for s in cargados if s.loteria in NOMBRES_VIP]
    clave = (fecha, len(cargados))
    if clave not in _cache_fuego:
        fuentes = [s for s in cargados if s.loteria in NOMBRES_OCULTO]
        por_dia: dict[date, list[db.Sorteo]] = defaultdict(list)
        for s in vip:
            if fecha - timedelta(days=DIAS_PRUEBA) <= s.fecha < fecha:
                por_dia[s.fecha].append(s)
        aciertos = jugados = 0
        for dia, del_dia in por_dia.items():
            parejas = _vip(vip, dia)[1]
            abiertos = libro_oculto.abiertos(libro_oculto.primeras_de(fuentes, dia))[0]
            fuego = {y for x in parejas for y in (x["numero"], x["inverso"]) if y in abiertos}
            for s in del_dia:
                jugados += len(fuego)
                aciertos += s.numeros[0] in fuego
        _cache_fuego.clear()
        _cache_fuego[clave] = _medir(aciertos, jugados, libro.PROB_PRIMERO)
    return _cache_fuego[clave]


_cache_fuego: dict = {}

# ------------------------------------------------------- Compartir (imagen)

PLANTILLA = Path(__file__).resolve().parent / "web" / "plantilla.png"
# Los flyers del Público y VIP: la app tapa los números y la fecha viejos y escribe los del día
FLYERS = {"/flyer_gratis.jpg": "flyer_gratis.jpg", "/flyer_vip.jpg": "flyer_vip.jpg",
          "/flyer_bingo.jpg": "flyer_bingo.jpg"}  # el de aciertos del Público (BINGO)
# Las letras de los flyers van dentro del proyecto para que funcionen sin depender de internet
FUENTES = {"/fuentes/archivo-black.woff2": "fuentes/archivo-black.woff2",
           "/fuentes/barlow-condensed-800.woff2": "fuentes/barlow-condensed-800.woff2"}
MAX_FILAS = 10   # filas que caben en la imagen
MAX_NUMEROS = 8  # números por fila

NOMBRE_METODO = {
    "oraculo": "El Oráculo", "indicadas": "Loterías indicadas", "fuertes": "Los 7 más fuertes",
    "master": "Master", "king": "Master King", "raya": "3 en raya", "josefina": "Josefina",
    "vip": "Público y VIP", "laboratorio": "Laboratorio", "formula": "La Fórmula",
}


def _fila(titulo: str, numeros, fuego=()) -> dict:
    nums = list(dict.fromkeys(n for n in numeros if n))[:MAX_NUMEROS]
    return {"titulo": titulo, "numeros": nums, "fuego": [n for n in nums if n in set(fuego)]}


def compartir(con, metodo: str, fecha: date) -> dict | None:
    """Los números recomendados de un método, en filas cortas listas para dibujar en una imagen."""
    def par(x):
        return [x["numero"]] + ([x["inverso"]] if x.get("inverso") and x["inverso"] != x["numero"] else [])
    filas: list[dict] = []
    nota = ""
    flyer = None
    if metodo == "oraculo":
        r = recomendaciones(con, fecha)
        if not r:
            return None
        por_lot: dict[str, list[str]] = {}
        for x in r["destacados"]:
            por_lot.setdefault(x["loteria"], []).append(x["numero"])
        filas = [_fila(l, ns) for l, ns in por_lot.items()]
    elif metodo == "indicadas":
        r = indicadas(con, fecha)
        if not r:
            return None
        filas = [_fila(l["nombre"], [j["numero"] for j in l["jugadas"]]) for l in r["loterias"]]
    elif metodo == "fuertes":
        r = fuertes(con, fecha)
        if not r:
            return None
        filas = [_fila(l["nombre"], [x["numero"] for x in l["numeros"]]) for l in r["loterias"]]
        nota = "Cada número se juega con su inverso"
    elif metodo == "master":
        r = master(con, fecha)
        if not r:
            return None
        filas = [_fila(l["nombre"], [x["numero"] for x in l["ranking"]]) for l in r["loterias"]]
    elif metodo == "king":
        r = master_king(con, fecha)
        if not r:
            return None
        filas = [_fila(l["nombre"], [x["numero"] for x in l["numeros"]]) for l in r["loterias"]]
    elif metodo == "raya":
        r = tres_en_raya(con, fecha)
        if not r:
            return None
        filas = [_fila("Jugada", [n for x in r["numeros"] for n in par(x)])]
        filas += [_fila(a["nombre"], [n for c in a["campos"] for n in c["siguen"]]) for a in r["abiertos"]]
    elif metodo == "josefina":
        r = josefina(con, fecha)
        if not r:
            return None
        filas = [_fila(l["nombre"], [x["numero"] for x in l["numeros"]]) for l in r["loterias"]]
        nota = "Cada número se juega con su V (al revés)"
    elif metodo == "vip":
        r = publico_vip(con, fecha)
        if not r:
            return None
        fuego = r.get("oculto", {}).get("fuego", [])
        filas = [_fila("Público", [n for x in r["publico"] for n in par(x)], fuego),
                 _fila("VIP", [n for x in r["vip"] for n in par(x)], fuego)]
        nota = "🔥 también los abre el Libro oculto" if fuego else ""
        # para los flyers: la bola grande de cada pareja (Grupo Gratis = Público, Grupo VIP = VIP)
        flyer = {"gratis": [x["numero"] for x in r["publico"]], "vip": [x["numero"] for x in r["vip"]]}
        # aciertos del Público ese día: solo cuando uno de sus números (o su inverso) salió de 1ra
        jugados = {n for x in r["publico"] for n in par(x)}
        flyer["aciertos"] = [{"loteria": res["nombre"], "numeros": res["numeros"], "acierto": res["numeros"][0],
                              "premio": 1}
                             for res in r["resultados"] if res["numeros"] and res["numeros"][0] in jugados]
    elif metodo == "laboratorio":
        r = laboratorio(con, fecha)
        if not r:
            return None
        filas = [_fila("Consenso", [c["numero"] for c in r["consenso"]])]
        nota = f"Los números en que más coinciden {r['metodos']} métodos"
    elif metodo == "formula":
        r = la_formula(con, fecha)
        if not r:
            return None
        filas = [_fila("Fórmula", [x["numero"] for x in r["origen"]["formula"]])]
        elegidas = [d["nombre"] for d in r["destinos"] if d.get("elegida")]
        nota = f"Juégalos en: {', '.join(elegidas)}" if elegidas else ""
    else:
        return None
    filas = [f for f in filas if f["numeros"]][:MAX_FILAS]
    return {"metodo": NOMBRE_METODO[metodo], "clave": metodo, "fecha": r["fecha"], "filas": filas, "nota": nota,
            "plantilla": PLANTILLA.exists(), "flyer": flyer}


def laboratorio(con, fecha: date) -> dict | None:
    """Jugada de consenso de todos los métodos, El Vigilante (sesgos en las máquinas) y la
    tabla de la verdad (cómo le ha ido a cada método contra el azar)."""
    hoy = datetime.now(recolector.ZONA_RD).date()
    fecha = min(fecha, hoy)
    metodos = [
        ("El Oráculo", recomendaciones, "oraculo"), ("Loterías indicadas", indicadas, "indicadas"),
        ("Los 7 más fuertes", fuertes, "fuertes"), ("Master", master, "master"),
        ("Master King", master_king, "king"), ("3 en raya", tres_en_raya, "raya"),
        ("Josefina", josefina, "josefina"), ("Público y VIP", publico_vip, "vip"),
        ("La Fórmula", la_formula, "formula"),
    ]
    respuestas = {}
    for nombre, fn, enlace in metodos:
        try:
            r = fn(con, fecha)
        except Exception as e:  # un método roto no tumba el laboratorio
            print(f"Laboratorio: {nombre} falló: {e}", file=sys.stderr)
            r = None
        if r:
            respuestas[nombre] = (r, enlace)
    if not respuestas:
        return None

    # 1. Consenso: cuántos métodos distintos recomiendan cada número
    votos: dict[str, list[str]] = defaultdict(list)
    for nombre, (r, _) in respuestas.items():
        for n in _numeros_de(nombre, r):
            votos[n].append(nombre)
    elegidos = sorted(votos, key=lambda n: (-len(votos[n]), n))[:CUANTOS_CONSENSO]
    reales = {s.loteria: s for s in db.cargar(con, hasta=fecha) if s.fecha == fecha and s.loteria in NOMBRES_VIP}
    # también cuenta si sale su inverso (20 -> 02); los dobles (22) no tienen otro inverso
    consenso = [{"numero": n, "votos": len(votos[n]), "metodos": sorted(votos[n]),
                 "inverso": n[::-1] if n[::-1] != n else None,
                 "en_primera": [l for l, s in reales.items() if s.numeros[0] == n],
                 "donde": [l for l, s in reales.items() if n in s.numeros],
                 "inv_primera": [l for l, s in reales.items() if n[::-1] != n and s.numeros[0] == n[::-1]],
                 "inv_donde": [l for l, s in reales.items() if n[::-1] != n and n[::-1] in s.numeros]}
                for n in elegidos]

    # 2. El Vigilante: todas las quinielas activas
    todos = db.cargar(con, hasta=fecha)
    por_lot: dict[str, list[db.Sorteo]] = defaultdict(list)
    for s in todos:
        if s.fecha < fecha and len(s.numeros) == 3 and all(len(n) == 2 and n.isdigit() for n in s.numeros):
            por_lot[s.loteria].append(s)
    activas = {l: ss for l, ss in por_lot.items()
               if len(ss) >= libro_vigilante.MIN_SORTEOS and (fecha - ss[-1].fecha).days <= DIAS_INACTIVA}
    vigilante = []
    for l, ss in activas.items():
        v = libro_vigilante.revisar(ss, len(activas))
        if v:
            vigilante.append({"loteria": l, "grupo": ss[-1].grupo, **v})
    vigilante.sort(key=lambda x: (x["p"], x["loteria"]))

    # 3. Tabla de la verdad: lo que cada método mide de sí mismo en los últimos días
    verdad = []
    for nombre, (r, enlace) in respuestas.items():
        p = r.get("prueba")
        if nombre == "El Oráculo":
            verdad.append(_verdad(nombre, "cualquier premio", r["oraculo"], enlace))
        elif nombre == "Loterías indicadas":
            verdad.append(_verdad(nombre, "cualquier premio", p[0], enlace))
        elif nombre == "Master":
            verdad.append(_verdad(nombre, "cualquier premio", p["cuatro"], enlace))
        elif nombre == "Público y VIP":
            verdad.append(_verdad("Público", "1er premio", p["publico"]["primera"], enlace))
            verdad.append(_verdad("VIP", "1er premio", p["vip"]["primera"], enlace))
        elif nombre == "La Fórmula":
            verdad.append(_verdad(nombre, "cualquier premio", p["elegidas"]["cualquiera"], enlace))
        elif p and "z" in p:
            verdad.append(_verdad(nombre, "cualquier premio", p, enlace))
    verdad.append(_verdad("🔥 Fuego (Libro oculto)", "1er premio", _prueba_fuego(con, fecha), "vip"))
    # con tantos métodos, alguno saldría "bueno" por suerte: se exige más (Bonferroni)
    z_exigido = round(_z_bonferroni(len(verdad)), 2)

    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat(),
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "metodos": len(respuestas),
        "consenso": consenso,
        "resultados": [{"nombre": l, "numeros": list(s.numeros)} for l, s in reales.items()],
        "vigilante": vigilante,
        "sesgos": sum(v["estado"] == "sesgo" for v in vigilante),
        "verdad": verdad,
        "z_exigido": z_exigido,
        "ganadores": [v["metodo"] for v in verdad if v["z"] >= z_exigido],
        "dias_prueba": DIAS_PRUEBA,
    }


def _z_bonferroni(pruebas: int, alfa: float = 0.05) -> float:
    """El Z que hay que pasar para que, entre `pruebas` métodos, ganarle al azar no sea suerte (una cola)."""
    objetivo = alfa / max(pruebas, 1)
    bajo, alto = 0.0, 6.0
    for _ in range(60):
        medio = (bajo + alto) / 2
        if 0.5 * math.erfc(medio / math.sqrt(2)) > objetivo:
            bajo = medio
        else:
            alto = medio
    return alto

# --------------------------------------------------------------- La Fórmula

# Los números salen de la Anguila de las 10 de la mañana y se juegan ese mismo día en estas
ORIGEN_FORMULA = "Anguila 10:00 AM"
LOTERIAS_FORMULA = LOTERIAS_VIP
NOMBRES_FORMULA = NOMBRES_VIP
DESTINOS_FORMULA = 3  # en cuántas loterías se recomienda jugarlos


def _cruces(todos: list[db.Sorteo]) -> list[tuple]:
    """Para cada sorteo de las loterías destino, los 6 números de la fórmula de la Anguila de
    las 10 de ese mismo día: (fecha, destino, ¿1ra?, aciertos, jugados)."""
    anguila = {s.fecha: set(libro_formula.formula(s.numeros)) for s in todos if s.loteria == ORIGEN_FORMULA}
    return [(s.fecha, s.loteria, s.numeros[0] in f, len(f & set(s.numeros)), len(f))
            for s in todos if s.loteria in NOMBRES_FORMULA and (f := anguila.get(s.fecha))]


def _puntaje(c: list[int]) -> float:
    """Aciertos en 1ra frente a lo que daría el azar, con +1 arriba y abajo para que pocos
    sorteos no manden (un acierto en 1ra de 1 sorteo no vale más que 20 de 200)."""
    return (c[0] + 1) / (c[2] * libro.PROB_PRIMERO + 1)


def _acumular(cuenta: dict, x: tuple):
    c = cuenta[x[1]]  # [aciertos en 1ra, aciertos, números jugados, sorteos]
    c[0], c[1], c[2], c[3] = c[0] + x[2], c[1] + x[3], c[2] + x[4], c[3] + 1


def _mejores(cuenta: dict) -> list[str]:
    return sorted(NOMBRES_FORMULA, key=lambda b: -_puntaje(cuenta[b]))[:DESTINOS_FORMULA]


def la_formula(con, fecha: date) -> dict | None:
    todos = [s for s in db.cargar(con, hasta=fecha) if s.loteria in NOMBRES_FORMULA or s.loteria == ORIGEN_FORMULA]
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    desde = fecha - timedelta(days=365 * AÑOS_FUERTES)
    cruces = [x for x in _cruces(todos) if x[0] >= desde]
    etiquetas = dict((n, e) for e, n in LOTERIAS_FORMULA)

    clave = (fecha, len(todos))
    if clave not in _cache_formula:
        # Cómo le fue: cada día de los DIAS_PRUEBA anteriores se eligieron las loterías solo con
        # lo que había antes de ese día, y se miró si su 1er premio era de la fórmula
        cuenta: dict = defaultdict(lambda: [0, 0, 0, 0])
        prueba = {"elegidas": [0, 0, 0, 0], "todas": [0, 0, 0, 0]}
        por_dia: dict[date, list[tuple]] = defaultdict(list)
        for x in cruces:
            if x[0] < fecha:
                por_dia[x[0]].append(x)
        for dia in sorted(por_dia):
            if dia >= fecha - timedelta(days=DIAS_PRUEBA):
                elegidas = _mejores(cuenta)
                for x in por_dia[dia]:
                    for parte in ["todas"] + (["elegidas"] if x[1] in elegidas else []):
                        c = prueba[parte]
                        c[0], c[1], c[2], c[3] = c[0] + x[2], c[1] + x[3], c[2] + x[4], c[3] + 1
            for x in por_dia[dia]:
                _acumular(cuenta, x)
        _cache_formula.clear()
        _cache_formula[clave] = {
            parte: {"sorteos": s, "primera": _medir(a1, j, libro.PROB_PRIMERO),
                    "cualquiera": _medir(a, j, motor.PROB_AZAR)}
            for parte, (a1, a, j, s) in prueba.items()}

    # Lo que pasó hasta el día anterior a `fecha`, para elegir las loterías de hoy
    cuenta = defaultdict(lambda: [0, 0, 0, 0])
    for x in cruces:
        if x[0] < fecha:
            _acumular(cuenta, x)
    elegidas = _mejores(cuenta)

    anguila = next((s for s in todos if s.loteria == ORIGEN_FORMULA and s.fecha == fecha), None)
    nums = libro_formula.formula(anguila.numeros) if anguila else []
    reales = {s.loteria: s for s in todos if s.fecha == fecha}
    destinos = []
    for b in sorted(NOMBRES_FORMULA, key=lambda b: -_puntaje(cuenta[b])):
        c = cuenta[b]
        real = reales.get(b)
        destinos.append({"etiqueta": etiquetas[b], "nombre": b, "sorteos": c[3],
                         "primera": _medir(c[0], c[2], libro.PROB_PRIMERO),
                         "cualquiera": _medir(c[1], c[2], motor.PROB_AZAR),
                         "elegida": b in elegidas,
                         "resultado": list(real.numeros) if real and nums else None,
                         "en_primera": real.numeros[0] in nums if real and nums else None,
                         "aciertos": len(set(nums) & set(real.numeros)) if real and nums else None})

    primer_dia = todos[0].fecha
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primer_dia else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "desde": max(desde, primer_dia).isoformat(),
        "cuantos": DESTINOS_FORMULA,
        "origen": {"nombre": ORIGEN_FORMULA, "numeros": list(anguila.numeros) if anguila else None,
                   "formula": [{"numero": n, "de": anguila.numeros[i // 2],
                                "texto": f"{i // 2 * 2 + 1}{anguila.numeros[i // 2]}{i // 2 * 2 + 2}"}
                               for i, n in enumerate(nums)]},
        "destinos": destinos,
        "dias": len({x[0] for x in cruces if x[0] < fecha}),
        "prueba": _cache_formula[clave],
        "dias_prueba": DIAS_PRUEBA,
    }


_cache_formula: dict = {}

# ------------------------------------------------------------------- Master

def _medir(aciertos: int, jugados: int, prob: float) -> dict:
    esperado = jugados * prob
    var = jugados * prob * (1 - prob)
    return {"aciertos": aciertos, "jugados": jugados, "esperado": round(esperado, 1),
            "vs_azar": round(aciertos / esperado, 3) if esperado else 0,
            "z": round((aciertos - esperado) / var ** .5, 2) if var else 0}


def master(con, fecha: date) -> dict | None:
    todos = db.cargar(con, hasta=fecha)
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    desde = fecha - timedelta(days=365 * AÑOS_FUERTES)
    prueba_desde = fecha - timedelta(days=DIAS_PRUEBA)
    nacional = {s.fecha: s.numeros[0] for s in todos
                if s.loteria == libro_master.DISPARADOR and desde <= s.fecha < fecha}
    por_loteria: dict[str, list[db.Sorteo]] = defaultdict(list)
    for s in todos:
        if s.loteria in libro_master.NOMBRES and s.fecha >= desde:
            por_loteria[s.loteria].append(s)

    numero = libro_master.disparo(nacional, fecha)
    fila = libro_master.LIBRO[numero] if numero else []
    tarjetas = []
    medidas = {"cuatro": [0, 0], "uno": [0, 0], "historial": [0, 0]}  # [aciertos, sorteos]
    for etiqueta, nombre in libro_master.DESTINOS:
        sorteos = por_loteria.get(nombre, [])
        h = [s for s in sorteos if s.fecha < fecha]
        real = next((s for s in sorteos if s.fecha == fecha), None)
        # Cómo le fue: cada día con Nacional Noche la noche anterior, sin ver el resultado
        for i, s in enumerate(h):
            t = libro_master.disparo(nacional, s.fecha)
            if t is None:
                continue
            f = libro_master.LIBRO[t]
            medidas["historial"][0] += bool(set(f) & set(s.numeros))
            medidas["historial"][1] += 1
            if s.fecha >= prueba_desde:
                orden = libro_master.seguimiento(f, nacional, h[:i], s.fecha)
                medidas["cuatro"][0] += bool(set(f) & set(s.numeros))
                medidas["uno"][0] += orden[0].numero in s.numeros
                medidas["cuatro"][1] += 1
                medidas["uno"][1] += 1
        if not fila or not h:
            continue
        salidos = set(real.numeros) if real else None
        tarjetas.append({
            "etiqueta": etiqueta,
            "nombre": nombre,
            "ranking": [{"numero": x.numero, "veces": x.veces, "sugerido": x.sugerido, "acerto": x.acerto,
                         "hace": x.hace, "probabilidad": round(x.probabilidad, 4),
                         "acierto": _salio(salidos, [x.numero])}
                        for x in libro_master.seguimiento(fila, nacional, h, fecha)],
            "sorteos": len(h),
            "resultado": list(real.numeros) if real else None,
        })

    p, primer_dia = motor.PROB_AZAR, todos[0].fecha
    p4 = 1 - (1 - p) ** 4
    return {
        "fecha": fecha.isoformat(),
        "hoy": hoy.isoformat(),
        "anterior": (fecha - timedelta(days=1)).isoformat() if fecha - timedelta(days=1) > primer_dia else None,
        "siguiente": (fecha + timedelta(days=1)).isoformat() if fecha < hoy else None,
        "nacional": {"numero": numero, "fecha": (fecha - timedelta(days=1)).isoformat(), "fila": fila},
        "loterias": tarjetas,
        "prueba": {
            "historial": _medir(*medidas["historial"], p4),
            "cuatro": _medir(*medidas["cuatro"], p4),
            "uno": _medir(*medidas["uno"], p),
        },
        "en_alguna": round(1 - (1 - p4) ** len(libro_master.DESTINOS), 4),
        "dias_prueba": DIAS_PRUEBA,
    }


_descargando = threading.Lock()


def actualizar(con) -> dict:
    """Descarga desde el último día guardado (o ayer, si es más reciente) hasta hoy."""
    hoy = datetime.now(recolector.ZONA_RD).date()
    ultimo = con.execute("SELECT MAX(fecha) FROM sorteos").fetchone()[0]
    desde = min(date.fromisoformat(ultimo), hoy - timedelta(days=1)) if ultimo else hoy - timedelta(days=1)
    nuevos = 0
    for f in recolector.dias_hacia_atras((hoy - desde).days + 1, hoy):
        nuevos += db.guardar(con, recolector.descargar_dia(f))
    return {"nuevos": nuevos}


def _actualizar_cada(ruta_db: Path, segundos: int):
    """En la nube: actualiza al arrancar y luego cada cierto tiempo, en segundo plano."""
    while True:
        with _descargando:
            con = db.conectar(ruta_db)
            try:
                print(f"Actualización automática: {actualizar(con)['nuevos']} sorteos nuevos", flush=True)
            except Exception as e:  # que un fallo de la página no tumbe el servidor
                print(f"Actualización automática fallida: {e}", flush=True)
            finally:
                con.close()
        time.sleep(segundos)


# --------------------------------------------------------------------- servidor

def crear_servidor(ruta_db: Path, puerto: int, host: str = "127.0.0.1",
                   publico: bool = False) -> ThreadingHTTPServer:
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *args):  # sin ruido en la terminal
            pass

        def _responder(self, codigo: int, cuerpo: bytes, tipo: str):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, datos, codigo: int = 200):
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self._responder(codigo, cuerpo, "application/json; charset=utf-8")

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                return self._responder(200, PAGINA.read_bytes(), "text/html; charset=utf-8")
            if url.path in FUENTES:
                return self._responder(200, (PAGINA.parent / FUENTES[url.path]).read_bytes(), "font/woff2")
            if url.path in FLYERS:
                return self._responder(200, (PAGINA.parent / FLYERS[url.path]).read_bytes(), "image/jpeg")
            if url.path == "/plantilla.png":
                if not PLANTILLA.exists():
                    return self._json({"error": "No hay plantilla"}, 404)
                return self._responder(200, PLANTILLA.read_bytes(), "image/png")
            con = db.conectar(ruta_db)
            try:
                if url.path == "/api/resumen":
                    return self._json({**resumen(con), "publico": publico})
                if url.path == "/api/dia":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        return self._json({"error": "Fecha no válida"}, 400)
                    return self._json(dia(con, fecha))
                if url.path == "/api/recomendaciones":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = recomendaciones(con, fecha, q.get("loteria"))
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/indicadas":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = indicadas(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/fuertes":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = fuertes(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/king":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = master_king(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/raya":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = tres_en_raya(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/josefina":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = josefina(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/vip":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = publico_vip(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/compartir":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = compartir(con, q.get("metodo", ""), fecha)
                    if datos is None:
                        return self._json({"error": "No hay números para ese método"}, 404)
                    return self._json(datos)
                if url.path == "/api/laboratorio":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = laboratorio(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/formula":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = la_formula(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/master":
                    try:
                        fecha = date.fromisoformat(q.get("fecha", ""))
                    except ValueError:
                        fecha = datetime.now(recolector.ZONA_RD).date()
                    datos = master(con, fecha)
                    if datos is None:
                        return self._json({"error": "Todavía no hay datos"}, 404)
                    return self._json(datos)
                if url.path == "/api/loteria":
                    datos = loteria(con, q.get("nombre", ""), int(q.get("n", 60)))
                    if datos is None:
                        return self._json({"error": "No hay datos de esa lotería"}, 404)
                    return self._json(datos)
                self._json({"error": "No encontrado"}, 404)
            finally:
                con.close()

        def do_POST(self):
            if urlparse(self.path).path != "/api/actualizar":
                return self._json({"error": "No encontrado"}, 404)
            if publico:  # en la nube se actualiza sola; nadie de fuera dispara descargas
                return self._json({"error": "Se actualiza automáticamente"}, 403)
            if not _descargando.acquire(blocking=False):
                return self._json({"error": "Ya se está descargando, espera un momento"}, 409)
            con = db.conectar(ruta_db)
            try:
                self._json(actualizar(con))
            except recolector.ErrorRecolector as e:
                self._json({"error": str(e)}, 502)
            finally:
                con.close()
                _descargando.release()

    # Por defecto solo accesible desde esta computadora; en la nube, host="0.0.0.0"
    return _Servidor((host, puerto), Manejador)


class _Servidor(ThreadingHTTPServer):
    # En Windows, reutilizar la dirección deja abrir dos servidores en el mismo puerto
    # y sigue respondiendo el viejo; así, el segundo falla con un aviso claro.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def iniciar(ruta_db: Path, puerto: int = 8000, abrir: bool = True):
    try:
        servidor = crear_servidor(ruta_db, puerto)
    except OSError:
        print(f"El puerto {puerto} ya está en uso. ¿Ya tienes la interfaz abierta en otra terminal?\n"
              f"Ciérrala con Ctrl+C, o usa otro puerto:  python main.py web --puerto {puerto + 1}")
        return
    url = f"http://localhost:{puerto}"
    print(f"Interfaz abierta en {url}  (Ctrl+C para cerrar)")
    if abrir:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")
    finally:
        servidor.server_close()


def iniciar_nube(ruta_db: Path, puerto: int):
    """Modo servidor público (Render, etc.): escucha en todas las interfaces y se actualiza solo."""
    servidor = crear_servidor(ruta_db, puerto, host="0.0.0.0", publico=True)
    threading.Thread(target=_actualizar_cada, args=(ruta_db, 3600), daemon=True).start()
    print(f"Sirviendo en el puerto {puerto}", flush=True)
    servidor.serve_forever()
