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
    POST /api/actualizar                 descarga los resultados de hoy y ayer
"""

from __future__ import annotations

import json
import sys
import threading
import time
import webbrowser
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, motor, recolector
from .reglas import TODAS as REGLAS
from .reglas import Contexto
from .reglas import indicadas as libro
from .reglas import master as libro_master

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


def fuertes(con, fecha: date) -> dict | None:
    todos = [s for s in db.cargar(con, hasta=fecha) if s.loteria in NOMBRES_FUERTES]
    if not todos:
        return None
    hoy = datetime.now(recolector.ZONA_RD).date()
    desde = fecha - timedelta(days=365 * AÑOS_FUERTES)
    prueba_desde = fecha - timedelta(days=DIAS_PRUEBA)

    # Se recorre en orden: antes de cada sorteo de la prueba se eligen los 7 con lo que
    # había hasta ese momento, así la prueba nunca ve el resultado que juega.
    ventana: dict[str, list[db.Sorteo]] = defaultdict(list)
    veces: dict[str, Counter] = defaultdict(Counter)
    primero: dict[str, Counter] = defaultdict(Counter)
    ultima: dict[str, dict[str, date]] = defaultdict(dict)
    sorteos = jugados = aciertos = con_acierto = 0
    reales: dict[str, db.Sorteo] = {}
    for s in todos:
        if s.fecha == fecha:
            reales[s.loteria] = s
            continue
        v = ventana[s.loteria]
        while v and v[0].fecha < s.fecha - timedelta(days=365 * AÑOS_FUERTES):
            viejo = v.pop(0)
            veces[s.loteria].subtract(viejo.numeros)
            primero[s.loteria][viejo.numeros[0]] -= 1
        if s.fecha >= prueba_desde and len(v) >= 30:
            elegidos = {n for par in _top(+veces[s.loteria], ultima[s.loteria],
                                          libro_master.LIBRO[v[-1].numeros[0]]) for n in par}
            sorteos += 1
            jugados += len(elegidos)
            ac = len(elegidos & set(s.numeros))
            aciertos += ac
            con_acierto += ac > 0
        v.append(s)
        veces[s.loteria].update(s.numeros)
        primero[s.loteria][s.numeros[0]] += 1
        for n in s.numeros:
            ultima[s.loteria][n] = s.fecha

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

    esperado = jugados * motor.PROB_AZAR
    var = jugados * motor.PROB_AZAR * (1 - motor.PROB_AZAR)
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
        "prueba": {
            "sorteos": sorteos, "jugados": jugados, "aciertos": aciertos, "con_acierto": con_acierto,
            "esperado": round(esperado, 1),
            "vs_azar": round(aciertos / esperado, 3) if esperado else 0,
            "z": round((aciertos - esperado) / var ** .5, 2) if var else 0,
            "prob_alguno": round(1 - (1 - motor.PROB_AZAR) ** (jugados / sorteos), 4) if sorteos else 0,
        },
        "dias_prueba": DIAS_PRUEBA,
    }


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
