"""La Fórmula: de cada sorteo salen 6 números.

A cada premio se le pone una cifra delante y otra detrás, contando 1-2 para el 1ro,
3-4 para el 2do y 5-6 para el 3ro, y lo que queda se parte en dos números:

    23-13-20  ->  1·23·2  3·13·4  5·20·6  ->  12 32  31 34  52 06
"""

from __future__ import annotations


def formula(numeros) -> list[str]:
    """("23", "13", "20") -> ["12", "32", "31", "34", "52", "06"]."""
    salida = []
    for i, n in enumerate(numeros[:3]):
        t = f"{2 * i + 1}{n}{2 * i + 2}"
        salida += [t[:2], t[2:]]
    return salida
