"""AQUÍ VAN TUS REGLAS.

Cada regla es una clase con un `nombre` y una función `predecir` que devuelve
los números a jugar. Dentro de `predecir` tienes `ctx` con todo el historial:

    ctx.ultimo              -> el sorteo anterior de esta lotería
    ctx.ultimo.numeros      -> sus números, p. ej. ("07", "45", "91")
    ctx.ultimos(10)         -> los últimos 10 sorteos
    ctx.frecuencias(30)     -> cuántas veces salió cada número en los últimos 30
    ctx.dias_sin_salir()    -> cuántos sorteos lleva cada número sin salir
    ctx.de_otra("Quiniela Leidsa") -> historial de otra lotería
    ctx.fecha               -> el día que se está prediciendo (ctx.fecha.weekday(): 0=lunes)

Ayudas: espejo("23") -> "32";  limpiar([...]) quita repetidos y formatea a 2 cifras.

Después de escribir la regla, añádela a la lista REGLAS de abajo.
"""

from .base import Contexto, Regla, espejo, limpiar  # noqa: F401


# --- Ejemplo: borra o cambia esta regla -----------------------------------
class PrimerPremioMasUno(Regla):
    nombre = "Primer premio +1"
    descripcion = "Juega el primer premio anterior sumándole 1 y su espejo."
    # Solo para estas loterías (quita la línea para aplicarla a todas):
    loterias = ["Lotería Nacional", "Quiniela Leidsa"]

    def predecir(self, ctx: Contexto) -> list[str]:
        siguiente = (int(ctx.ultimo.numeros[0]) + 1) % 100
        return limpiar([siguiente, espejo(f"{siguiente:02d}")])


REGLAS = [
    PrimerPremioMasUno(),
]
