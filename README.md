# Loterías RD

Descarga los resultados de todas las loterías dominicanas desde
[loteriasdominicanas.com](https://loteriasdominicanas.com), los guarda en una base de datos
local y aplica tus reglas para sugerir números. También prueba cada regla con los sorteos
pasados para ver si de verdad funciona mejor que el azar.

## Instalación (una sola vez)

1. Instala [Python 3.10 o más nuevo](https://www.python.org/downloads/) (en Windows, marca
   **"Add Python to PATH"**) y la extensión **Python** de VS Code.
2. Abre esta carpeta en VS Code (**Archivo → Abrir carpeta**).
3. Abre la terminal (**Terminal → Nueva terminal**) y ejecuta:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## Uso

```bash
python main.py historial --dias 90     # descarga los últimos 90 días (tarda un minuto)
python main.py actualizar              # descarga lo de hoy y ayer (úsalo cada día)
python main.py web                     # interfaz en el navegador (http://localhost:8000)
python main.py loterias                # lista las loterías guardadas
python main.py ver "Quiniela Leidsa"   # últimos resultados de una lotería
python main.py predecir                # predicciones de hoy según tus reglas
python main.py probar --dias 60        # cómo les habría ido a tus reglas
python main.py probar --detalle        # lo mismo, desglosado por lotería
```

También puedes lanzarlos desde **Ejecutar y depurar** (Ctrl+Shift+D) en VS Code.

¿Sin internet o quieres probar primero? `python main.py demo` crea datos al azar y luego
`python main.py --demo probar`.

## Escribir tus reglas

Todo se hace en **`loterias/reglas/mis_reglas.py`**. Ahí está explicado qué datos tienes
disponibles y hay un ejemplo listo para copiar. En `loterias/reglas/ejemplos.py` hay más
modelos (espejo, calientes, atrasados).

## Estructura

```
main.py                    comandos
loterias/recolector.py     lee la página de resultados
loterias/db.py             base de datos (datos/loterias.db)
loterias/motor.py          aplica las reglas y hace la prueba histórica
loterias/reglas/           tus reglas y los ejemplos
tests/                     pruebas automáticas
```

## De dónde salen los datos

La página carga los resultados desde su propia API en JSON
(`api.loteriasdominicanas.com`), y el recolector la consulta directamente: una sola
consulta por día trae los ~110 juegos de las 13 loterías (Leidsa, Nacional, Real, Loteka,
Americanas, Nueva York, Florida, La Primera, La Suerte, LoteDom, Anguila, King Lottery y
Haiti Bolet). Hay historial desde abril de 2026; para bajarlo todo:
`python main.py historial --desde 2026-04-01`.

Si algún día deja de descargar, todo lo que depende de la página está en
`loterias/recolector.py`.

## Importante

Los sorteos son aleatorios: ninguna regla puede predecirlos. La prueba histórica existe para
comprobarlo con datos reales. Juega solo lo que estés dispuesto a perder.
