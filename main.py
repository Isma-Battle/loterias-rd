"""Loterías RD: resultados y predicciones según tus reglas.

Uso (desde la terminal de VS Code):
    python main.py actualizar                 # descarga los resultados de hoy
    python main.py historial --dias 90        # descarga los últimos 90 días
    python main.py loterias                   # qué loterías hay guardadas
    python main.py ver "Quiniela Leidsa"      # últimos resultados de una lotería
    python main.py predecir                   # predicciones para hoy
    python main.py probar --dias 60           # qué tal habrían funcionado tus reglas
    python main.py web                        # interfaz en el navegador
    python main.py demo                       # crea datos de prueba (sin internet)
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, timedelta

from loterias import db, motor, recolector
from loterias.reglas import TODAS as REGLAS

RUTA_DEMO = db.RUTA_DB.parent / "demo.db"


def cmd_actualizar(args, con):
    fechas = [date.today() - timedelta(days=1), date.today()]  # ayer por si faltó algo
    _descargar(con, fechas)


def cmd_historial(args, con):
    if args.desde:
        desde = date.fromisoformat(args.desde)
        fechas = list(recolector.dias_hacia_atras((date.today() - desde).days + 1))
    else:
        fechas = list(recolector.dias_hacia_atras(args.dias))
    _descargar(con, fechas)


def _descargar(con, fechas):
    total = 0
    for i, f in enumerate(fechas, 1):
        print(f"[{i}/{len(fechas)}] {f:%d-%m-%Y} ...", end=" ", flush=True)
        try:
            sorteos = recolector.descargar_dia(f)
        except recolector.ErrorRecolector as e:
            print(f"\n{e}")
            sys.exit(1)
        nuevos = db.guardar(con, sorteos)
        total += nuevos
        print(f"{len(sorteos)} sorteos, {nuevos} nuevos")
    print(f"\nListo: {total} sorteos nuevos guardados.")
    if total == 0 and len(fechas) > 1:
        print("Si esperabas resultados, puede que la página haya cambiado:\n"
              "revisa loterias/recolector.py. (Hay historial desde abril de 2026.)")


def cmd_loterias(args, con):
    filas = db.loterias(con)
    if not filas:
        print("Todavía no hay datos. Ejecuta: python main.py historial --dias 30")
        return
    grupo_actual = None
    for loteria, grupo, n in filas:
        if grupo != grupo_actual:
            print(f"\n{grupo}")
            grupo_actual = grupo
        print(f"  {loteria:<40} {n:>5} sorteos")


def cmd_ver(args, con):
    sorteos = db.cargar(con, args.loteria)
    if not sorteos:
        print(f"No hay sorteos de '{args.loteria}'. Mira los nombres con: python main.py loterias")
        return
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    for s in sorteos[-args.n:]:
        print(f"{dias[s.fecha.weekday()]} {s.fecha:%d-%m-%Y}  {' - '.join(s.numeros)}")


def cmd_predecir(args, con):
    fecha = date.fromisoformat(args.fecha) if args.fecha else date.today()
    preds = motor.predecir(db.cargar(con), REGLAS, fecha)
    if not preds:
        print("No hay predicciones. ¿Descargaste el historial? python main.py historial --dias 30")
        return
    todos = db.cargar(con)
    pesos = motor.simular([s for s in todos if s.fecha < fecha], REGLAS,
                          fecha - timedelta(days=60)).pesos
    por_loteria: dict[str, dict[str, list[str]]] = {}
    for p in preds:
        if not args.loteria or p.loteria == args.loteria:
            por_loteria.setdefault(p.loteria, {})[p.regla] = p.numeros

    print(f"Predicciones para el {fecha:%d-%m-%Y}\n")
    for loteria, reglas in por_loteria.items():
        jugadas = motor.oraculo(reglas, pesos)
        print(loteria)
        print(f"  {'★ ' + motor.ORACULO:<28} "
              + "  ".join(f"{j.numero} ({j.fuerza:.0%})" for j in jugadas))
        for regla, numeros in reglas.items():
            print(f"    {regla:<26} {'  '.join(numeros)}")


def cmd_probar(args, con):
    desde = date.today() - timedelta(days=args.dias) if args.dias else None
    loterias = [args.loteria] if args.loteria else None
    resultados = motor.probar(db.cargar(con), REGLAS, desde, loterias)
    resultados = [r for r in resultados if r.jugadas]
    if not resultados:
        print("No hay suficientes datos para probar las reglas.")
        return

    print(f"Prueba histórica {'(últimos %d días)' % args.dias if args.dias else '(todo el historial)'}\n")
    print(f"{'Regla':<28}{'Sorteos':>9}{'Números':>9}{'Aciertos':>10}{'Tasa':>8}"
          f"{'Azar':>8}{'vs azar':>9}{'Z':>7}")
    for r in sorted(resultados, key=lambda r: -r.vs_azar):
        print(f"{r.regla:<28}{r.jugadas:>9}{r.numeros_jugados:>9}{r.aciertos:>10}"
              f"{r.tasa:>8.2%}{motor.PROB_AZAR:>8.2%}{r.vs_azar:>8.2f}x{r.z:>7.1f}")

    print("\nCómo leerlo:")
    print("  Tasa    = de cada número que jugó la regla, qué porcentaje salió.")
    print("  Azar    = lo que saldría jugando números al azar (≈2.97 % por número).")
    print("  vs azar = 1.00x es igual que el azar; más de 1 es mejor.")
    print("  Z       = entre -2 y +2 la diferencia se explica por pura suerte.")
    print("            Con varias reglas, alguna pasará de +2 por casualidad (prueba 'demo').")
    print("            Una regla solo merece atención si supera +3 y lo repite con datos nuevos.")

    if args.detalle:
        for r in resultados:
            print(f"\n{r.regla}")
            for lot, (jugados, ac) in sorted(r.detalle.items()):
                print(f"  {lot:<40} {ac:>4}/{jugados:<5} {ac / jugados:6.2%}")


def cmd_web(args, _con):
    from loterias import web
    if os.environ.get("PORT"):  # lo define el servicio de la nube (Render, Railway...)
        return web.iniciar_nube(db.RUTA_DB, int(os.environ["PORT"]))
    web.iniciar(RUTA_DEMO if args.demo else db.RUTA_DB, args.puerto, abrir=not args.no_abrir)


def cmd_demo(args, _con):
    """Datos inventados para probar el sistema sin internet."""
    if RUTA_DEMO.exists():
        RUTA_DEMO.unlink()
    con = db.conectar(RUTA_DEMO)
    loterias = [("Lotería Nacional", "Nacional"), ("Quiniela Leidsa", "Leidsa"),
                ("Quiniela Loteka", "Loteka"), ("Anguila 10:00 AM", "Anguila")]
    sorteos = []
    for f in recolector.dias_hacia_atras(180, date.today() - timedelta(days=1)):
        for nombre, grupo in loterias:
            nums = tuple(f"{random.randint(0, 99):02d}" for _ in range(3))
            sorteos.append(db.Sorteo(nombre, grupo, f, nums))
    db.guardar(con, sorteos)
    print(f"Creados {len(sorteos)} sorteos de prueba (al azar) en {RUTA_DEMO}")
    print("Pruébalos con:  python main.py --demo probar   o   python main.py --demo predecir")


def main():
    p = argparse.ArgumentParser(description="Resultados y predicciones de loterías dominicanas")
    p.add_argument("--demo", action="store_true", help="usar la base de datos de prueba")
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("actualizar", help="descargar resultados de hoy y ayer")
    h = sub.add_parser("historial", help="descargar resultados de días anteriores")
    h.add_argument("--dias", type=int, default=30)
    h.add_argument("--desde", help="fecha inicial AAAA-MM-DD")
    sub.add_parser("loterias", help="listar loterías guardadas")
    v = sub.add_parser("ver", help="ver últimos resultados de una lotería")
    v.add_argument("loteria")
    v.add_argument("-n", type=int, default=15)
    pr = sub.add_parser("predecir", help="predicciones según tus reglas")
    pr.add_argument("--fecha", help="AAAA-MM-DD (por defecto hoy)")
    pr.add_argument("--loteria")
    pb = sub.add_parser("probar", help="probar las reglas con sorteos pasados")
    pb.add_argument("--dias", type=int, help="solo los últimos N días")
    pb.add_argument("--loteria")
    pb.add_argument("--detalle", action="store_true", help="desglose por lotería")
    w = sub.add_parser("web", help="abrir la interfaz en el navegador")
    w.add_argument("--puerto", type=int, default=8000)
    w.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    sub.add_parser("demo", help="crear datos de prueba al azar")

    args = p.parse_args()
    comandos = {
        "actualizar": cmd_actualizar, "historial": cmd_historial, "loterias": cmd_loterias,
        "ver": cmd_ver, "predecir": cmd_predecir, "probar": cmd_probar, "web": cmd_web, "demo": cmd_demo,
    }
    con = None if args.comando in ("demo", "web") else db.conectar(RUTA_DEMO if args.demo else db.RUTA_DB)
    comandos[args.comando](args, con)


if __name__ == "__main__":
    # Para que los acentos se vean bien en la terminal de Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
