import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loterias import motor  # noqa: E402
from loterias.db import Sorteo  # noqa: E402
from loterias.recolector import leer_nombres, leer_sesiones  # noqa: E402
from loterias.reglas import indicadas  # noqa: E402
from loterias.reglas.base import Contexto, Regla  # noqa: E402

SITIO = {"siteCompanies": [
    {"title": "Leidsa", "siteGames": [
        {"game_id": "a1", "title": "Quiniela Leidsa"},
        {"game_id": "a2", "title": "Loto Pool"},
        {"game_id": "a3", "title": "Super Kino TV"},
    ]},
    {"title": "Loteria Real", "siteGames": [{"game_id": "b1", "title": "Loto  Pool"}]},
    {"title": "King Lottery", "siteGames": [{"game_id": "c1", "title": "Pick 3 Día"}]},
]}

DIA = "2026-10-17T04:00:00.000Z"   # medianoche del 17 en hora dominicana
SESIONES = [
    {"game_id": "a1", "sessions": [{"date": DIA, "score": [["07", "45", "91"]]}]},
    {"game_id": "a2", "sessions": [{"date": DIA, "score": [["02", "03", "04", "05", "07"]]}]},
    {"game_id": "a3", "sessions": [{"date": DIA, "score": []}]},            # sin celebrar
    {"game_id": "b1", "sessions": [{"date": "2026-10-16T04:00:00.000Z",     # de otro día
                                    "score": [["11", "12", "13", "14"]]}]},
    {"game_id": "c1", "sessions": [{"date": DIA, "score": [["9", "7", "3", "xYz_imagen"]]}]},
]


class TestRecolector(unittest.TestCase):
    def test_nombres_repetidos_llevan_la_loteria(self):
        n = leer_nombres(SITIO)
        self.assertEqual(n["a1"], ("Quiniela Leidsa", "Leidsa"))
        self.assertEqual(n["a2"][0], "Loto Pool (Leidsa)")
        self.assertEqual(n["b1"][0], "Loto Pool (Loteria Real)")

    def test_lee_sesiones(self):
        s = {x.loteria: x for x in leer_sesiones(SESIONES, leer_nombres(SITIO), date(2026, 10, 17))}
        self.assertEqual(set(s), {"Quiniela Leidsa", "Loto Pool (Leidsa)", "Pick 3 Día"})
        q = s["Quiniela Leidsa"]
        self.assertEqual((q.numeros, q.fecha, q.grupo), (("07", "45", "91"), date(2026, 10, 17), "Leidsa"))
        self.assertTrue(q.es_quiniela)
        self.assertFalse(s["Loto Pool (Leidsa)"].es_quiniela)
        # Las cifras sueltas no se rellenan, para que un Pick 3 no parezca una quiniela
        self.assertEqual(s["Pick 3 Día"].numeros, ("9", "7", "3"))
        self.assertFalse(s["Pick 3 Día"].es_quiniela)


class ReglaQueVeElFuturo(Regla):
    """Comprueba que el motor nunca le muestra a la regla el resultado a predecir."""
    nombre = "Espía"

    def predecir(self, ctx: Contexto):
        assert all(s.fecha < ctx.fecha for s in ctx.historial)
        assert all(s.fecha < ctx.fecha for s in ctx.todas)
        return list(ctx.ultimo.numeros)


class TestMotor(unittest.TestCase):
    def setUp(self):
        self.datos = [
            Sorteo("X", "G", date(2026, 1, d), (f"{d:02d}", "50", "60")) for d in range(1, 11)
        ]

    def test_sin_mirar_el_futuro(self):
        r = motor.probar(self.datos, [ReglaQueVeElFuturo()])[0]
        self.assertEqual(r.jugadas, 9)
        # "50" y "60" salen siempre, así que acierta 2 de 3 cada día
        self.assertEqual(r.aciertos, 18)

    def test_predecir(self):
        p = motor.predecir(self.datos, [ReglaQueVeElFuturo()], date(2026, 1, 11))
        self.assertEqual(p[0].numeros, ["10", "50", "60"])


class TestIndicadas(unittest.TestCase):
    def test_volteo(self):
        self.assertEqual(indicadas.jugar("69v 61 09v"), ["69", "96", "61", "09", "90"])

    def test_combina_las_fuentes(self):
        # Lunes 19: sale 05-00-33 -> 05 repite como 50, el libro da 05-50 y 33-88-...
        ultimo = Sorteo("Quiniela Leidsa", "Leidsa", date(2026, 10, 18), ("05", "00", "33"))
        a = indicadas.analizar(Contexto("Quiniela Leidsa", date(2026, 10, 19), [ultimo], [ultimo]))
        self.assertEqual(a.fuentes["Rosita · repite"], ["50", "05", "01"])
        self.assertIn("50", a.fuentes["Libro oculto"])
        # 2 fuentes cada uno: 01 (00 repite como 01 + 10v del libro), 50 y 88 (día + libro)
        self.assertEqual({j.numero for j in a.jugadas[:3]}, {"01", "50", "88"})
        self.assertEqual(a.jugadas[0].votos, 2)

    def test_primer_premio_solo_mira_el_primero(self):
        # Solo el 05 dispara: repite (50, 05) y libro (05-50); el 00 y el 33 no cuentan
        ultimo = Sorteo("Quiniela Leidsa", "Leidsa", date(2026, 10, 18), ("05", "00", "33"))
        a = indicadas.primer_premio(Contexto("Quiniela Leidsa", date(2026, 10, 19), [ultimo], [ultimo]))
        self.assertEqual(a.fuentes["Rosita · repite"], ["50", "05"])
        self.assertEqual(a.fuentes["Libro oculto"], ["50"])
        self.assertEqual((a.jugadas[0].numero, a.jugadas[0].votos), ("50", 2))


class TestFuertes(unittest.TestCase):
    def test_los_mas_salidos_sin_contar_el_dia(self):
        import sqlite3
        from loterias import db, web
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE sorteos (loteria TEXT, grupo TEXT, fecha TEXT, numeros TEXT)")
        datos = [Sorteo("Quiniela Leidsa", "Leidsa", date(2026, 1, d), ("07", "45", f"{d:02d}"))
                 for d in range(1, 11)]
        datos.append(Sorteo("Quiniela Leidsa", "Leidsa", date(2026, 1, 11), ("99", "98", "97")))
        db.guardar(con, datos)
        d = web.fuertes(con, date(2026, 1, 11))
        nums = d["loterias"][0]["numeros"]
        self.assertEqual(len(nums), 7)
        self.assertEqual([n["numero"] for n in nums[:2]], ["07", "45"])  # 10 veces cada uno
        self.assertNotIn("99", [n["numero"] for n in nums])               # el resultado del día no cuenta
        self.assertEqual(d["loterias"][0]["resultado"], ["99", "98", "97"])


if __name__ == "__main__":
    unittest.main()
