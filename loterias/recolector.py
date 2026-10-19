"""Descarga los resultados desde loteriasdominicanas.com.

La página carga los números con JavaScript desde su propia API (JSON):
  - {API}/sites/env            -> todas las loterías y juegos, con sus nombres
  - {API}/sessions?date=...    -> el resultado de cada juego en esa fecha

Con una sola consulta a `sessions` se obtienen TODOS los juegos de un día.
La API tiene historial desde abril de 2026, aproximadamente.

Si algún día la página cambia, lo único que hay que tocar es este archivo:
`cargar_nombres` (nombres de los juegos) y `leer_sesiones` (resultados).
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import requests

from .db import Sorteo

API = "https://api.loteriasdominicanas.com/dominicana"

# Las fechas de la API están en UTC; República Dominicana es UTC-4 todo el año.
ZONA_RD = timezone(timedelta(hours=-4))

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "es-DO,es;q=0.9",
    "Origin": "https://loteriasdominicanas.com",
    "Referer": "https://loteriasdominicanas.com/",
}


class ErrorRecolector(Exception):
    pass


def _pedir(sesion: requests.Session, ruta: str, **params):
    try:
        r = sesion.get(f"{API}/{ruta}", params=params, headers=CABECERAS, timeout=30)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        raise ErrorRecolector(f"No se pudo leer {ruta}: {e}") from e


# ------------------------------------------------------------------ nombres

def leer_nombres(sitio: dict) -> dict[str, tuple[str, str]]:
    """game_id -> (nombre del juego, grupo/lotería), a partir de `sites/env`."""
    juegos = []
    for empresa in sitio.get("siteCompanies", []):
        grupo = " ".join(str(empresa.get("title", "")).split()) or "Otros"
        for juego in empresa.get("siteGames", []):
            nombre = " ".join(str(juego.get("title", "")).split())
            juegos.append((juego.get("game_id"), nombre, grupo))

    # Algunos nombres se repiten entre loterías (p. ej. "Super Palé" o "Loto Pool"),
    # así que a esos les añadimos la lotería para distinguirlos.
    repetidos = Counter(nombre for _, nombre, _ in juegos)
    return {
        gid: (f"{nombre} ({grupo})" if repetidos[nombre] > 1 else nombre, grupo)
        for gid, nombre, grupo in juegos if gid
    }


_NOMBRES: dict[str, tuple[str, str]] | None = None


def cargar_nombres(sesion: requests.Session) -> dict[str, tuple[str, str]]:
    """Se descarga una sola vez por ejecución."""
    global _NOMBRES
    if _NOMBRES is None:
        _NOMBRES = leer_nombres(_pedir(sesion, "sites/env"))
    return _NOMBRES


# --------------------------------------------------------------- resultados

def _fecha_rd(texto: str) -> date:
    """'2026-10-17T04:00:00.000Z' -> 17-10-2026 (hora dominicana)."""
    dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    return dt.astimezone(ZONA_RD).date()


def _numeros(score) -> tuple[str, ...]:
    """Aplana [["07", "45", "91"]] y descarta lo que no son números
    (la API a veces mete identificadores de imágenes o casillas vacías).

    Se dejan tal cual vienen: "07" en quinielas, "9" en Pick 3 / Numbers."""
    filas = score if isinstance(score, list) else []
    return tuple(
        str(n).strip()
        for fila in filas
        for n in (fila if isinstance(fila, list) else [fila])
        if str(n).strip().isdigit()
    )


def leer_sesiones(datos: list, nombres: dict[str, tuple[str, str]],
                  fecha_pedida: date) -> list[Sorteo]:
    """Extrae los sorteos de la respuesta de `sessions` celebrados en `fecha_pedida`.

    La API devuelve el último sorteo de cada juego hasta esa fecha, así que los
    juegos que no se celebraron ese día traen uno anterior: esos se descartan."""
    encontrados: dict[tuple[str, date], Sorteo] = {}
    for juego in datos if isinstance(datos, list) else []:
        gid = juego.get("game_id", "")
        nombre, grupo = nombres.get(gid, (f"Juego {gid[-6:]}", "Otros"))
        for sesion in juego.get("sessions") or []:
            try:
                fecha = _fecha_rd(sesion["date"])
            except (KeyError, TypeError, ValueError):
                continue
            numeros = _numeros(sesion.get("score"))
            if fecha != fecha_pedida or not numeros:
                continue  # otro día, o sorteo aún no celebrado
            encontrados.setdefault((nombre, fecha), Sorteo(nombre, grupo, fecha, numeros))
    return list(encontrados.values())


def descargar_dia(fecha: date | None = None, sesion: requests.Session | None = None,
                  pausa: float = 0.3) -> list[Sorteo]:
    """Todos los sorteos publicados para un día (por defecto, hoy)."""
    fecha = fecha or datetime.now(ZONA_RD).date()
    sesion = sesion or _SESION
    nombres = cargar_nombres(sesion)
    # Medianoche en RD expresada en UTC, que es como la página hace la consulta
    inicio = datetime(fecha.year, fecha.month, fecha.day, tzinfo=ZONA_RD)
    datos = _pedir(sesion, "sessions",
                   date=inicio.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    time.sleep(pausa)  # no saturar la página
    return leer_sesiones(datos, nombres, fecha)


_SESION = requests.Session()

def dias_hacia_atras(dias: int, hasta: date | None = None):
    hasta = hasta or date.today()
    for i in range(dias - 1, -1, -1):
        yield hasta - timedelta(days=i)
