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
    def test_libro(self):
        from loterias.reglas import king
        self.assertEqual(king.LIBRO["00"], ["81", "49", "25"])          # capítulo 05
        self.assertEqual(king.LIBRO["07"], ["17", "19", "97", "70", "12", "61"])  # 05 y 07 juntos
        self.assertEqual(king.LIBRO["24"], ["14", "34", "05", "98"])

    def test_los_4_mas_salidos(self):
        from collections import Counter
        from loterias.reglas import king
        # Sale 07 (abre 17 19 97 70 12 61) y 99 (abre 00); 50 no empieza ninguna fila
        veces = Counter({"17": 1, "19": 9, "97": 3, "70": 7, "12": 3, "61": 5, "00": 8})
        k = king.jugar(("07", "99", "50"), veces, {"12": date(2026, 1, 5)})
        self.assertEqual([x["numero"] for x in k], ["19", "00", "70", "61"])
        veces["61"] = 0
        k = king.jugar(("07",), veces, {"12": date(2026, 1, 5)})
        self.assertEqual([x["numero"] for x in k], ["19", "70", "12", "97"])  # 12 salió más reciente


class TestPublicoVip(unittest.TestCase):
    def test_prioriza_el_primer_premio(self):
        import sqlite3
        from loterias import db, web
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE sorteos (loteria TEXT, grupo TEXT, fecha TEXT, numeros TEXT)")
        d = lambda i: date(2026, 1, i)  # noqa: E731
        # 12 es 1er premio de Gana Más todos los días. En la Real, 34 lo fue los 5 primeros días y
        # 89 los 5 últimos: el reciente pesa más. 77 sale en todos los sorteos pero nunca de 1ra.
        datos = [Sorteo("Gana Más", "Nacional", d(i), ("12", "77", f"{i + 50:02d}")) for i in range(1, 11)]
        datos += [Sorteo("Quiniela Real", "Loteria Real", d(i), ("34" if i <= 5 else "89", "77", f"{i + 60:02d}"))
                  for i in range(1, 11)]
        datos += [Sorteo("Quiniela Leidsa", "Leidsa", d(i), ("99", "99", "99")) for i in range(1, 11)]
        datos.append(Sorteo("Gana Más", "Nacional", d(11), ("12", "00", "01")))
        db.guardar(con, datos)
        r = web.publico_vip(con, d(11))
        self.assertEqual(r["sorteos"], 20)  # Leidsa no está en este método
        self.assertEqual([(x["numero"], x["inverso"], x["primero"]) for x in r["publico"]],
                         [("12", "21", 10), ("89", "98", 5), ("34", "43", 5)])
        self.assertEqual(r["vip"], [])  # solo 3 parejas han salido de 1ra
        self.assertEqual(r["publico"][0]["probabilidad"], 0.5)  # 12 fue 1ro en la mitad de los sorteos
        self.assertEqual(r["resultados"][0]["primera"], "publico")  # el 12 salió de 1ra en Gana Más


class TestFormula(unittest.TestCase):
    def test_el_ejemplo(self):
        from loterias.reglas.formula import formula
        # 1·23·2  3·13·4  5·20·6
        self.assertEqual(formula(("23", "13", "20")), ["12", "32", "31", "34", "52", "06"])

    def test_de_la_anguila_a_donde_sale_en_primera(self):
        import sqlite3
        from loterias import db, web
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE sorteos (loteria TEXT, grupo TEXT, fecha TEXT, numeros TEXT)")
        d = lambda i: date(2026, 1, i)  # noqa: E731
        # La Anguila de las 10 saca siempre 23-13-20 (fórmula: 12 32 31 34 52 06) y ese mismo día
        # la Quiniela Real saca el 12 de 1ra; la Nacional nunca saca nada de la fórmula
        datos = [Sorteo("Anguila 10:00 AM", "Anguila", d(i), ("23", "13", "20")) for i in range(1, 12)]
        datos += [Sorteo("Quiniela Real", "Loteria Real", d(i), ("12", "77", "88")) for i in range(1, 12)]
        datos += [Sorteo("Lotería Nacional", "Nacional", d(i), ("90", "91", "93")) for i in range(1, 12)]
        datos += [Sorteo("Quiniela Leidsa", "Leidsa", d(i), ("12", "12", "12")) for i in range(1, 12)]
        db.guardar(con, datos)
        r = web.la_formula(con, d(11))
        self.assertEqual(r["origen"]["numeros"], ["23", "13", "20"])
        self.assertEqual([x["numero"] for x in r["origen"]["formula"]], ["12", "32", "31", "34", "52", "06"])
        real = r["destinos"][0]
        self.assertEqual((real["nombre"], real["elegida"], real["primera"]["aciertos"]), ("Quiniela Real", True, 10))
        self.assertTrue(real["en_primera"])  # el día 11 también salió el 12 de 1ra
        self.assertNotIn("Quiniela Leidsa", [x["nombre"] for x in r["destinos"]])  # no está entre las 10


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


class TestJosefina(unittest.TestCase):
    def test_guia(self):
        from loterias.reglas import josefina
        self.assertEqual(len(josefina.LIBRO), 100)
        self.assertEqual(josefina.LIBRO["30"], ["85", "15", "70"])   # el ejemplo del video
        self.assertEqual(josefina.LIBRO["01"], ["10", "00", "68"])   # el 100 de la guía es el 00
        self.assertEqual(josefina.LIBRO["00"], ["10", "98", "50"])
        self.assertEqual(josefina.LIBRO["98"], ["43", "04", "02"])

    def test_jala_lo_de_ayer_en_las_indicadas(self):
        from loterias.reglas import josefina
        d = lambda i: date(2026, 1, i)  # noqa: E731
        datos = {
            # ayer en la Nacional: 30 jala 85 15 70 (4 puntos cada uno)
            ("Lotería Nacional", d(9)): Sorteo("Lotería Nacional", "Nacional", d(9), ("30", "60", "99")),
            # ayer en Leidsa (2.ª indicada de la Nacional): 37 jala 13 73 93 (3 puntos)
            ("Quiniela Leidsa", d(9)): Sorteo("Quiniela Leidsa", "Leidsa", d(9), ("37", "88", "88")),
            # anteayer en la Nacional salió el 06: jala 15 60 23, pero el 60 ya salió ayer
            ("Lotería Nacional", d(8)): Sorteo("Lotería Nacional", "Nacional", d(8), ("06", "05", "05")),
            # La Primera no es indicada para la Nacional: no cuenta
            ("La Primera Día", d(9)): Sorteo("La Primera Día", "La Primera", d(9), ("50", "50", "50")),
        }
        j = josefina.jugar("Lotería Nacional", d(10), lambda l, f: datos.get((l, f)))
        nums = {x["numero"]: x for x in j["jugada"]}
        self.assertEqual(j["jugada"][0]["numero"], "15")
        self.assertEqual(nums["15"]["puntos"], 12)         # lo jalan el 30 y el 60 de ayer y el 06 de anteayer
        self.assertEqual(nums["15"]["inverso"], "51")
        self.assertNotIn("60", nums)                        # ya salió: secuencia cerrada
        self.assertNotIn("03", nums)                        # 50 es de La Primera
        self.assertEqual(j["pales"], [])                    # el palé 06-15 solo se da el día siguiente
        datos[("Quiniela Leidsa", d(9))] = Sorteo("Quiniela Leidsa", "Leidsa", d(9), ("06", "88", "88"))
        j = josefina.jugar("Lotería Nacional", d(10), lambda l, f: datos.get((l, f)))
        self.assertEqual(j["pales"], [])                    # palés solo de la misma lotería
        j = josefina.jugar("Quiniela Leidsa", d(10), lambda l, f: datos.get((l, f)))
        self.assertEqual(j["pales"], [["06", "15"]])
        self.assertEqual(len(j["jugada"]), josefina.CUANTOS)

    def test_web(self):
        import sqlite3
        from loterias import db, web
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE sorteos (loteria TEXT, grupo TEXT, fecha TEXT, numeros TEXT)")
        d = lambda i: date(2026, 1, i)  # noqa: E731
        db.guardar(con, [Sorteo("Lotería Nacional", "Nacional", d(i), ("30", "85", "15")) for i in range(1, 11)])
        r = web.josefina(con, d(10))
        nac = r["loterias"][0]
        self.assertEqual(nac["nombre"], "Lotería Nacional")
        self.assertEqual(nac["resultado"], ["30", "85", "15"])
        self.assertTrue(any(x["acierto"] for x in nac["numeros"]))
        self.assertGreater(r["prueba"]["aciertos"], 0)


class TestLibroOculto(unittest.TestCase):
    def test_libro(self):
        from loterias.reglas import oculto
        sec = {s["texto"]: s for s in oculto.LIBRO}
        self.assertEqual(sec["00-06v-10v"]["siguen"], ["06", "60", "10", "01"])   # la v es volteado
        self.assertEqual(sec["01v-56v"]["primero"], ["01", "10"])
        self.assertTrue(sec["01-29"]["fuerte"])
        # todos llevan su inverso, tengan "v" o no
        self.assertEqual(sec["02-07-25-75"]["primero"], ["02", "20"])
        self.assertEqual(sec["02-07-25-75"]["siguen"], ["07", "70", "25", "52", "75", "57"])
        self.assertEqual(sec["44-49-99"]["primero"], ["44"])

    def test_abiertos_y_fuego(self):
        import sqlite3
        from loterias import db, web
        from loterias.reglas import oculto
        d = lambda i: date(2026, 1, i)  # noqa: E731
        prim = oculto.primeras_de([Sorteo("Florida Día", "Americanas", d(7), ("29", "00", "00")),   # 3 días atrás
                                   Sorteo("Florida Día", "Americanas", d(6), ("37", "00", "00"))],  # 4: no cuenta
                                  d(10))
        nums, abiertas = oculto.abiertos(prim)
        self.assertEqual([a["secuencia"] for a in abiertas], ["29-10", "29v-39-36", "92v-10v-39v"])  # 92v también es el 29
        self.assertIn("10", nums)
        self.assertNotIn("45", nums)
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE sorteos (loteria TEXT, grupo TEXT, fecha TEXT, numeros TEXT)")
        db.guardar(con, [Sorteo("Lotería Nacional", "Nacional", d(i), ("10" if i < 9 else "29", "44", "15"))
                         for i in range(1, 10)])
        r = web.publico_vip(con, d(10))
        self.assertIn("10", r["oculto"]["fuego"])            # 10/01 es del Público y lo abre el 29
        self.assertTrue(any("10" in x["fuego"] for x in r["publico"] + r["vip"]))


class TestVigilante(unittest.TestCase):
    def _sorteos(self, n, elegir):
        return [Sorteo("X", "X", date(2026, 1, 1), elegir(i)) for i in range(n)]

    def test_maquina_pareja(self):
        import random
        from loterias.reglas import vigilante
        r = random.Random(3)
        ss = self._sorteos(400, lambda i: tuple(f"{r.randrange(100):02d}" for _ in range(3)))
        v = vigilante.revisar(ss, 30)
        self.assertEqual(v["universo"], 100)
        self.assertNotEqual(v["estado"], "sesgo")

    def test_maquina_sesgada(self):
        import random
        from loterias.reglas import vigilante
        r = random.Random(4)
        # el 07 sale muchísimo más que los demás, en todo el historial
        ss = self._sorteos(400, lambda i: tuple("07" if r.random() < .15 else f"{r.randrange(100):02d}" for _ in range(3)))
        v = vigilante.revisar(ss, 30)
        self.assertEqual(v["estado"], "sesgo")
        self.assertEqual(v["mas_salidos"][0]["numero"], "07")

    def test_juego_corto_no_es_sesgo(self):
        import random
        from loterias.reglas import vigilante
        r = random.Random(5)
        ss = self._sorteos(300, lambda i: tuple(f"{r.randrange(51):02d}" for _ in range(3)))  # como Pega 3 Más
        v = vigilante.revisar(ss, 30)
        self.assertEqual(v["universo"], 51)
        self.assertNotEqual(v["estado"], "sesgo")
        self.assertIsNone(vigilante.revisar(ss[:50], 30))   # pocos sorteos

    def test_z_exigido(self):
        from loterias import web
        self.assertAlmostEqual(web._z_bonferroni(1), 1.645, places=2)
        self.assertGreater(web._z_bonferroni(11), 2.5)


class TestCompartir(unittest.TestCase):
    def test_numeros_para_la_imagen(self):
        import sqlite3
        from loterias import db, web
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE sorteos (loteria TEXT, grupo TEXT, fecha TEXT, numeros TEXT)")
        d = lambda i: date(2026, 1, i)  # noqa: E731
        db.guardar(con, [Sorteo("Lotería Nacional", "Nacional", d(i), ("10" if i < 9 else "29", "44", "15"))
                         for i in range(1, 10)])
        r = web.compartir(con, "vip", d(10))
        self.assertEqual(r["metodo"], "Público y VIP")
        self.assertEqual([f["titulo"] for f in r["filas"]][0], "Público")
        self.assertIn("10", r["filas"][0]["numeros"])
        self.assertIn("10", r["filas"][0]["fuego"])                       # el 29 de 1ra abre el 10
        self.assertTrue(all(len(f["numeros"]) <= web.MAX_NUMEROS for f in r["filas"]))
        self.assertIsNone(web.compartir(con, "no-existe", d(10)))
        # aciertos: el día 9 la Nacional dio 29-44-15; el 10 es del Público -> no; se mira el día 9
        r9 = web.compartir(con, "vip", d(9))
        jugados = {n for f in r9["filas"][:1] for n in f["numeros"]}
        esperados = ["29"] if "29" in jugados else []                   # solo cuenta la 1ra
        self.assertEqual([a["acierto"] for a in r9["flyer"]["aciertos"]], esperados)


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


class TestMasterKA(unittest.TestCase):
    def test_ejemplos_del_video(self):
        from loterias.reglas import master_ka as m
        # capítulo 5: lo que dice el video
        self.assertEqual(m.CAPITULO_5["69"], ["15", "22"])
        self.assertEqual(m.CAPITULO_5["57"], ["64", "46"])
        self.assertEqual(m.CAPITULO_5["95"], ["40"])
        self.assertEqual(m.CAPITULO_5["20"], ["02", "14", "41"])
        # capítulos 4 y 13: 15 -> 69, 40 -> 95, 08 -> 57
        self.assertEqual(m.pales("15"), ["69"])
        self.assertEqual(m.pales("40"), ["95"])
        self.assertEqual(m.pales("08"), ["57"])
        self.assertEqual(m.CAPITULO_6["57"], "75")

    def test_cuenta_el_mas_fuerte(self):
        from loterias.reglas import master_ka as m
        ayer = date(2026, 1, 1)
        todas = [Sorteo("La Primera Día", "La Primera", ayer, ("95", "01", "02")),
                 Sorteo("Primera Noche", "La Primera", ayer, ("95", "03", "04")),
                 Sorteo("New York Noche", "Americanas", ayer, ("69", "05", "06")),
                 Sorteo("Quiniela Leidsa", "Leidsa", ayer, ("60", "07", "08"))]
        ctx = Contexto("Quiniela Real", date(2026, 1, 2), todas[:1], todas)
        # 95 -> 40 dos veces; 59-95 del capítulo 6 también suma; 69 y 60 -> 15 dos veces
        self.assertEqual(m.mas_fuertes(m.conteo(m.numeros_de_ayer(ctx)), 2), ["15", "40"])
        self.assertEqual(m.MasterPale().predecir(ctx)[0], "15")


if __name__ == "__main__":
    unittest.main()
