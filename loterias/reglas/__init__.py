from . import avanzadas, ejemplos, mis_reglas
from .base import Contexto, Regla

# Todas las reglas que consulta el Oráculo. Para desactivar un grupo, quítalo de esta suma.
TODAS = ejemplos.REGLAS + avanzadas.REGLAS + mis_reglas.REGLAS

__all__ = ["TODAS", "Contexto", "Regla"]
