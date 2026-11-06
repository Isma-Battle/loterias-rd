"""El Vigilante: busca loterías cuya máquina no sea pareja (unos números salen más que otros).

Es la única forma en que se le ha ganado de verdad a un juego de azar (como las ruletas
desbalanceadas). Para no engañarse con la suerte:

  1. Prueba de chi-cuadrado: ¿los números salen parejo? Con muchas loterías, alguna saldrá
     "rara" por pura suerte, así que se exige p < 0.05 / número de loterías (Bonferroni).
  2. Confirmación con datos nuevos: los números más salidos en la primera mitad del historial
     tienen que seguir saliendo de más en la segunda mitad (que no se usó para escogerlos).

Solo si pasa las dos cosas el sesgo se da por confirmado y se juegan sus números.
"""

from __future__ import annotations

import math
from collections import Counter

MIN_SORTEOS = 100   # con menos no se puede decir nada
ALFA = 0.05
CALIENTES = 5       # números de la 1ra mitad que se comprueban en la 2da
Z_CONFIRMA = 2.0    # en la 2da mitad tienen que salir de más con esta fuerza


def universo(numeros) -> int:
    """Cuántos números distintos tiene el juego (00-99 = 100; Pega 3 Más va del 00 al 50)."""
    mayor = max(int(n) for n in numeros)
    return 100 if mayor >= 90 else mayor + 1


def chi_cuadrado(conteo: Counter, total: int, k: int) -> tuple[float, float]:
    """Chi-cuadrado de uniformidad y su p-valor (aproximación de Wilson-Hilferty)."""
    e = total / k
    x2 = sum((conteo.get(f"{i:02d}", 0) - e) ** 2 / e for i in range(k))
    gl = k - 1
    z = ((x2 / gl) ** (1 / 3) - (1 - 2 / (9 * gl))) / math.sqrt(2 / (9 * gl))
    return x2, 0.5 * math.erfc(z / math.sqrt(2))


def _z(veces: int, total: int, k: int) -> float:
    p = 1 / k
    return (veces - total * p) / math.sqrt(total * p * (1 - p))


def revisar(sorteos, n_loterias: int) -> dict | None:
    """`sorteos`: los de UNA lotería (quiniela de 3 números de 2 cifras), del más viejo al más nuevo."""
    if len(sorteos) < MIN_SORTEOS:
        return None
    numeros = [n for s in sorteos for n in s.numeros]
    k = universo(numeros)
    conteo = Counter(numeros)
    x2, p = chi_cuadrado(conteo, len(numeros), k)

    mitad = len(sorteos) // 2
    a = Counter(n for s in sorteos[:mitad] for n in s.numeros)
    b = Counter(n for s in sorteos[mitad:] for n in s.numeros)
    ta, tb = 3 * mitad, 3 * (len(sorteos) - mitad)
    calientes = sorted(a, key=lambda n: (-a[n], n))[:CALIENTES]
    # ¿los calientes de antes siguen calientes después? (juntos, como un solo grupo)
    z_despues = _z(sum(b[n] for n in calientes), tb, k / len(calientes))

    limite = ALFA / max(n_loterias, 1)
    if p < limite and z_despues >= Z_CONFIRMA:
        estado = "sesgo"
    elif p < ALFA:
        estado = "vigilar"
    else:
        estado = "justa"
    total = len(numeros)
    mas = sorted(conteo, key=lambda n: (-conteo[n], n))[:3]
    return {
        "sorteos": len(sorteos),
        "universo": k,
        "chi2": round(x2, 1),
        "p": round(p, 5),
        "limite": round(limite, 5),
        "z_despues": round(z_despues, 2),
        "calientes": calientes,
        "estado": estado,
        "mas_salidos": [{"numero": n, "veces": conteo[n], "esperado": round(total / k, 1),
                         "z": round(_z(conteo[n], total, k), 2)} for n in mas],
    }
