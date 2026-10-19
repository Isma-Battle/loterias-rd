"""Interfaz web local para ver los resultados guardados.

    python main.py web      ->  abre http://localhost:8000 en el navegador

Solo usa la librería estándar de Python. La página está en loterias/web/index.html
y pide los datos a estas rutas (todas devuelven JSON):

    GET  /api/resumen                    loterías guardadas y rango de fechas
    GET  /api/dia?fecha=AAAA-MM-DD       todos los resultados de un día
    GET  /api/loteria?nombre=...&n=60    historial y estadísticas de una lotería
    GET  /api/recomendaciones?fecha=...  números recomendados por las reglas para ese día
         (&loteria=... para una sola)
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
