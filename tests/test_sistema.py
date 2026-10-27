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
        self.assertEqual(a.fuentes["Master"], ["02", "07", "52", "57"])  # el 05 señala la fila del 02
        # 2 fuentes cada uno: 01 (00 repite como 01 + 10v del libro), 07 (Master + día),
        # 50 y 88 (día + libro)
        self.assertEqual({j.numero for j in a.jugadas[:4]}, {"01", "07", "50", "88"})
        self.assertEqual(a.jugadas[0].votos, 2)

    def test_primer_premio_solo_mira_el_primero(self):
        # Solo el 05 dispara: repite (50, 05) y libro (05-50); el 00 y el 33 no cuentan
        ultimo = Sorteo("Quiniela Leidsa", "Leidsa", date(2026, 10, 18), ("05", "00", "33"))
        a = indicadas.primer_premio(Contexto("Quiniela Leidsa", date(2026, 10, 19), [ultimo], [ultimo]))
        self.assertEqual(a.fuentes["Rosita · repite"], ["50", "05"])
        self.assertEqual(a.fuentes["Libro oculto"], ["50"])
        # 07 (Master + volteo del 70 del lunes) y 50 (repite + libro) empatan con 2 fuentes
        self.assertEqual([(j.numero, j.votos) for j in a.jugadas[:2]], [("07", 2), ("50", 2)])


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
        self.assertEqual([(n["numero"], n["inverso"]) for n in nums[:2]], [("07", "70"), ("45", "54")])
        # 01 y 10 salieron una vez cada uno: como pareja suman 2 y pasan delante de los demás
        self.assertEqual((nums[2]["numero"], nums[2]["inverso"], nums[2]["veces"]), ("10", "01", 2))
        # 07 sale 11 veces (el día 7 sale dos veces: 07-45-07) y 70 ninguna: la pareja suma 11
        self.assertEqual((nums[0]["veces"], nums[0]["detalle"], nums[0]["primero"]), (11, [11, 0], 10))
        self.assertEqual(nums[0]["fuerza_primera"], 1.0)  # 07 fue 1er premio en los 10 sorteos
        todos = {x for n in nums for x in (n["numero"], n["inverso"])}
        self.assertNotIn("99", todos)  # el resultado del día no cuenta
        self.assertEqual(d["loterias"][0]["resultado"], ["99", "98", "97"])


class TestMasterKing(unittest.TestCase):
    def test_puntos(self):
        from collections import Counter
        from loterias import web
        # 7 parejas fuertes con fuerza 10, 9 ... 4; el 99 casi no sale
        veces = Counter({f"{i}{i + 1}": 10 - i for i in range(7)} | {"99": 1})
        fila = ["01", "06", "51", "56"]  # 01 es el I de los fuertes (pareja 01-10)
        k = web._king(veces, {}, fila)
        self.assertEqual(len(k), 7)
        self.assertEqual((k[0]["numero"], k[0]["puntos"], k[0]["puesto"], k[0]["master"]), ("01", 11, 1, True))
        # 56 es el VI de los fuertes y está en la fila: 2 + 4. Las de la fila que no son fuertes
        # (4 puntos) entran detrás del IV; el V (45) y el VII (67) se quedan fuera
        self.assertEqual([(x["numero"], x["puntos"]) for x in k[1:]],
                         [("12", 6), ("56", 6), ("23", 5), ("34", 4), ("06", 4), ("51", 4)])


class TestTresEnRaya(unittest.TestCase):
    def test_libro(self):
        from loterias.reglas import raya
        self.assertEqual(raya.LIBRO["00"], ["81", "49", "25"])
        self.assertEqual(raya.LIBRO["93"], ["39", "37", "73"])
        self.assertEqual(len(raya.LIBRO), 99)  # 00 a 99 sin el 20

    def test_junta_todas_las_loterias(self):
        from collections import Counter
        from loterias.reglas import raya
        d = lambda i: date(2026, 1, i)  # noqa: E731
        a = [Sorteo("A", "G", d(i), n) for i, n in enumerate([("00", "33", "44"), ("52", "77", "88"),
             ("00", "33", "44"), ("25", "77", "88"), ("00", "33", "44")], 1)]
        b = [Sorteo("B", "G", d(i), n) for i, n in enumerate([("12", "33", "44"), ("65", "66", "88"),
             ("12", "11", "77")], 1)]
        historiales = {"A": a, "B": b}
        veces = Counter(n for h in historiales.values() for s in h for n in s.numeros)
        j = raya.jugar(historiales, veces)
        # A abre el campo del 00 (81, 49, 25); B el del 12 (56, 66) y el del 11 (45).
        # 25/52 salió 2 veces detrás de un 00 en A; 56/65 y 66 una vez detrás de un 12 en B
        self.assertEqual([(x["numero"], x["inverso"], x["despues"], x["campos"]) for x in j],
                         [("25", "52", 2, ["00"]), ("65", "56", 1, ["12"]), ("66", "66", 1, ["12"])])


class TestMaster(unittest.TestCase):
    def test_libro(self):
        from loterias.reglas import master
        self.assertEqual(len(master.LIBRO), 100)
        self.assertEqual(master.LIBRO["01"], ["10", "15", "60", "65"])  # el ejemplo del capítulo 12
        self.assertEqual(master.LIBRO["95"], ["44", "49", "94", "99"])

    def test_seguimiento_solo_la_fila_de_la_nacional(self):
        from loterias.reglas import master
        # La Nacional Noche saca 01 cada noche; al día siguiente Gana Más saca el 15
        nacional = {date(2026, 1, d): "01" for d in range(1, 11)}
        h = [Sorteo("Gana Más", "Nacional", date(2026, 1, d), ("15", "33", "44")) for d in range(2, 11)]
        fila = master.LIBRO[master.disparo(nacional, date(2026, 1, 11))]
        r = master.seguimiento(fila, nacional, h, date(2026, 1, 11))
        self.assertEqual(sorted(x.numero for x in r), ["10", "15", "60", "65"])  # ningún otro número
        self.assertEqual((r[0].numero, r[0].sugerido, r[0].acerto), ("15", 9, 9))
        self.assertGreater(r[0].probabilidad, r[1].probabilidad)


if __name__ == "__main__":
    unittest.main()
