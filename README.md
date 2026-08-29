# Base de datos de precios de acciones

Base historica propia de precios diarios (OHLCV + columnas ajustadas), que se
actualiza sola todos los dias habiles con GitHub Actions y queda versionada en
este mismo repositorio.

- **Fuente principal:** Tiingo (tickers de EE.UU.)
- **Fuente secundaria:** Stooq (tickers con punto, ej. `SMSN.UK`)
- **Salida:** un CSV por ticker en `data/`, ej. `data/KO.csv`
- **Sin dependencias:** solo Python 3 de la libreria estandar

## Estructura

```
tickers.txt              la lista que editas tu (un ticker por linea)
actualizar_precios.py    el script
data/                    un CSV por ticker (lo crea el script)
estado.json              ultima revision y ultima fecha de cada ticker
.github/workflows/       el workflow que lo corre solo
```

Columnas de cada CSV:

```
Date, Open, High, Low, Close, Volume,
AdjOpen, AdjHigh, AdjLow, AdjClose, AdjVolume,
Dividend, SplitFactor
```

Las columnas `Adj*` vienen ajustadas por splits y dividendos (metodologia CRSP
de Tiingo). Para graficar precios usa `Close`; para calcular retornos de largo
plazo usa `AdjClose`. En los tickers que vienen de Stooq las columnas `Adj*`
repiten el precio, porque Stooq entrega la serie ya ajustada.

## Puesta en marcha

### 1. Crear el repositorio

En GitHub: **New repository** → nombre `base-datos-acciones` → **Private** →
sin README (ya hay uno aqui). Despues, desde la carpeta del proyecto:

```bash
git init
git add .
git commit -m "Version inicial"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/base-datos-acciones.git
git push -u origin main
```

> **Ojo con Google Drive:** no conviene tener la carpeta `.git` dentro de una
> carpeta que sincroniza Drive; el sincronizador toca archivos internos de git
> y termina rompiendo el repo. Copia estos archivos a una carpeta local
> (por ejemplo `C:\proyectos\base-datos-acciones`) y trabaja el repo ahi.

### 2. Cargar el token de Tiingo

1. En Tiingo: **Account → API → Token**, y copia el token.
2. En GitHub: **Settings → Secrets and variables → Actions → New repository
   secret**.
3. Nombre exacto: `TIINGO_TOKEN`. Valor: el token.

El token nunca se escribe en el codigo ni queda en los CSV.

### 3. Primera carga del historico

En la pestana **Actions → Actualizar precios → Run workflow**, con
`full_refresh` en `false`. La lista actual tiene 43 tickers, asi que entra
completa en una sola corrida (el plan gratis permite 50 requests por hora).
Si algun dia la lista pasa de ~45, el script corta y la corrida siguiente
retoma por los tickers mas atrasados; no se pierde nada.

Si prefieres no esperar, puedes correrlo en tu PC:

```bash
set TIINGO_TOKEN=tu-token        # Windows CMD
python actualizar_precios.py
```

## Uso diario

No hay que hacer nada: el workflow corre de lunes a viernes despues del cierre
de EE.UU. y hace commit de lo que cambio. Para agregar o sacar acciones basta
editar `tickers.txt` y hacer commit; la proxima corrida baja el historico
completo de lo nuevo.

Reglas de `tickers.txt`:

- Un ticker por linea; todo lo que va despues de `#` es comentario.
- Un ticker **con punto** (ej. `SMSN.UK`) se toma como mercado fuera de EE.UU.
  y se busca en Stooq en vez de Tiingo.

## Limites del plan gratis de Tiingo

| | Gratis | Power (USD 30/mes) |
|---|---|---|
| Requests por hora | 50 | 10.000 |
| Requests por dia | 1.000 | 100.000 |
| Simbolos unicos al mes | 500 | practicamente sin tope |

Con 43 tickers no se toca ninguno de los tres limites. El unico que podria
apretar es el de 50 por hora si la lista crece: por eso el script corta la
corrida en 45 requests (`MAX_TIINGO`) y la retoma en la corrida siguiente,
empezando siempre por los tickers mas atrasados.

## Ejecucion manual y variables

| Variable | Para que sirve |
|---|---|
| `TIINGO_TOKEN` | Token de la API (obligatorio para tickers de EE.UU.) |
| `MAX_TIINGO` | Tope de requests por corrida (default 45) |
| `FULL_REFRESH` | `1` para rebajar todo el historico desde cero |
| `DATA_DIR` | Carpeta de salida (default `data`) |

```bash
python actualizar_precios.py KO MCD    # fuerza solo esos dos tickers
```

## Detalles que conviene saber

- **Splits:** si aparece un split nuevo, las columnas ajustadas cambian hacia
  atras. El script lo detecta y vuelve a bajar el historico completo de ese
  ticker automaticamente.
- **Correcciones de la fuente:** cada actualizacion vuelve a pedir los ultimos
  10 dias y sobrescribe lo que haya cambiado.
- **Tickers sin datos:** no rompen la corrida. Quedan anotados en `estado.json`
  con el motivo y aparecen en el resumen del log de Actions.
- **Stooq:** bloquea por IP cuando recibe muchas consultas. Si un ticker de
  Stooq falla, la corrida sigue igual y lo reintenta al dia siguiente.
