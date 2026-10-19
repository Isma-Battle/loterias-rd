"""Base de datos local (SQLite) con todos los sorteos descargados."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RUTA_DB = Path(__file__).resolve().parent.parent / "datos" / "loterias.db"


@dataclass(frozen=True)
class Sorteo:
    loteria: str        # "Quiniela Leidsa", "Anguila 10:00 AM", ...
    grupo: str          # "Leidsa", "Anguila", ...
    fecha: date
    numeros: tuple[str, ...]  # siempre como texto con 2 cifras: ("07", "45", "91")

    @property
    def es_quiniela(self) -> bool:
        """Sorteo de 3 números del 00 al 99 (quinielas, Anguila, americanas día/noche...)."""
        return len(self.numeros) == 3 and all(len(n) == 2 for n in self.numeros)


def conectar(ruta: Path = RUTA_DB) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sorteos (
            loteria  TEXT NOT NULL,
            grupo    TEXT NOT NULL,
            fecha    TEXT NOT NULL,          -- AAAA-MM-DD
            numeros  TEXT NOT NULL,          -- "07-45-91"
            PRIMARY KEY (loteria, fecha)
        )
        """
    )
    return con


def guardar(con: sqlite3.Connection, sorteos: list[Sorteo]) -> int:
    """Guarda sorteos nuevos. Devuelve cuántos se añadieron (ignora repetidos)."""
    antes = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO sorteos (loteria, grupo, fecha, numeros) VALUES (?, ?, ?, ?)",
        [(s.loteria, s.grupo, s.fecha.isoformat(), "-".join(s.numeros)) for s in sorteos],
    )
    con.commit()
    return con.total_changes - antes


def cargar(con: sqlite3.Connection, loteria: str | None = None,
           hasta: date | None = None) -> list[Sorteo]:
    """Sorteos ordenados del más antiguo al más reciente."""
    sql = "SELECT loteria, grupo, fecha, numeros FROM sorteos WHERE 1=1"
    params: list = []
    if loteria:
        sql += " AND loteria = ?"
        params.append(loteria)
    if hasta:
        sql += " AND fecha <= ?"
        params.append(hasta.isoformat())
    sql += " ORDER BY fecha, loteria"
    return [
        Sorteo(l, g, date.fromisoformat(f), tuple(n.split("-")))
        for l, g, f, n in con.execute(sql, params)
    ]


def loterias(con: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """(lotería, grupo, cantidad de sorteos guardados)."""
    return list(con.execute(
        "SELECT loteria, grupo, COUNT(*) FROM sorteos GROUP BY loteria, grupo ORDER BY grupo, loteria"
    ))
