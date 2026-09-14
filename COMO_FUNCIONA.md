# Cómo funciona esta base de datos

Referencia rápida del proyecto: qué se ejecuta, en qué orden, dónde, y para qué.

## La cadena diaria, en orden

| # | Cuándo | Dónde | ¿PC? | Qué corre | Para qué sirve | Lee → Escribe |
|---|---|---|---|---|---|---|
| 1 | 20:00 Chile, lun-vie | GitHub | No | El workflow se dispara solo | Es el despertador: pone en marcha todo lo demás | — |
| 2 | enseguida | GitHub | No | `actualizar_precios.py` | Trae el cierre del día de cada acción y lo agrega al histórico | `tickers.txt` + `estado.json` → `data\*.csv` |
| 3 | enseguida | GitHub | No | `indicadores.py --generar` | Arma las velas semanales y calcula el RSI con su banda de 5 años | `data\*.csv` → `indicadores\*` |
| 4 | enseguida | GitHub | No | El paso de git del workflow | Guarda lo que cambió, con fecha y historial reversible | lo modificado → un commit |
| 5 | 22:00 Chile | GitHub | No | Repite los pasos 2 a 4 | Red de seguridad: si la primera corrida falló, esta la cubre | — |
| 6 | 20:30 Chile | Tu PC | **Sí** | Tarea programada: `git pull` | Baja lo nuevo a tu carpeta, para trabajar con datos frescos | GitHub → `C:\proyectos\base-datos-acciones` |
| 7 | Al abrir el archivo | Excel | **Sí** | Power Query, con Actualizar todo | Lleva el RSI a Mecenas sin copiar y pegar nada | `resumen_rsi.csv` → hoja `3_Tecnico_ElliottRSI` |

Los pasos 2 y 3 producen, el 4 conserva, el 1 y el 5 coordinan, y el 6 y 7 distribuyen hacia donde uno trabaja.

El orden de 2 y 3 importa: primero los precios, después los indicadores calculados sobre esos precios. Invertido, el RSI se calcularía sobre los datos de ayer.

## Dónde vive cada archivo

| Archivo | Servidor GitHub | Tu PC |
|---|---|---|
| `tickers.txt` | ✓ el que manda | copia |
| `actualizar_precios.py` | ✓ se ejecuta aquí | copia, se puede correr a mano |
| `indicadores.py` | ✓ se ejecuta aquí | copia, se puede correr a mano |
| `data\*.csv` | ✓ se generan aquí | copia que baja el `git pull` |
| `indicadores\*` | ✓ se generan aquí | copia que baja el `git pull` |
| `Cartera_Mecenas.xlsx` | no está | ✓ solo vive aquí |
| `probar_stooq.py` | copia | ✓ se corre aquí, porque Stooq bloquea a los servidores |

Los pasos 1 al 5 ocurren enteramente en un computador de GitHub, con el PC apagado. Los pasos 6 y 7 son los únicos que pasan en la máquina propia, y los dos son de lectura: bajar una copia y leerla desde Excel. El PC nunca genera datos.

Consecuencia práctica: cambiar de computador no cuesta nada. Se instala git, se clona el repositorio, se recrea la tarea programada, y se está donde mismo.

La última fila de la tabla es la excepción: `probar_stooq.py` tiene que correr en el PC porque Stooq rechaza las consultas que vienen de centros de datos.

## Qué hay en cada archivo de salida

### `data\<TICKER>.csv` — el histórico diario

Una fila por jornada de bolsa.

| Columna | Qué es |
|---|---|
| `Date` | Fecha de la rueda |
| `Open, High, Low, Close` | Precios de esa jornada, tal como se transaron |
| `Volume` | Acciones transadas |
| `AdjOpen … AdjClose` | Los mismos precios corregidos por splits **y** dividendos (metodología CRSP) |
| `AdjVolume` | Volumen corregido |
| `Dividend` | Dividendo pagado ese día |
| `SplitFactor` | Factor de split; 1 si no hubo |

Para graficar el precio se usa `Close`. Para calcular rentabilidad de largo plazo, `AdjClose`.

### `indicadores\resumen_rsi.csv` — una fila por acción

| Columna | Qué es |
|---|---|
| `Ticker` | La acción |
| `Semana` | Último día operado de la semana del dato |
| `Close` | Cierre de esa semana, ajustado por splits |
| `RSI` | RSI semanal de 14 períodos, método de Wilder |
| `RSI_max_5a` / `RSI_min_5a` | Techo y piso que ese RSI tocó en las últimas 260 semanas |
| `Fecha_max` / `Fecha_min` | Cuándo tocó esos extremos |
| `Posicion` | Dónde cae el RSI de hoy dentro de esa banda, de 0 a 100 |
| `Semanas_ventana` | Cuántas semanas alcanzó a usar; 260 es la ventana completa |
| `Semanas_totales` | Cuánta historia tiene esa acción en la base |
| `Lectura` | La traducción en palabras: piso, techo, parte alta, parte baja |

`Posicion` es la lectura más útil porque es comparable entre acciones: un 8,7 en MCD y un 8,7 en TSLA significan lo mismo, aunque sus RSI absolutos sean muy distintos.

Mecenas solo consume cuatro de estas columnas: `Ticker`, `RSI`, `RSI_min_5a` y `RSI_max_5a`.

### `indicadores\semanal\<TICKER>.csv` — la serie semanal completa

Las mismas columnas de arriba pero para todas las semanas de la historia de esa acción, no solo la última. Es el archivo para graficar y para el análisis de ondas.

## Dos convenciones que conviene recordar

**El RSI se calcula sobre precios ajustados solo por splits**, no por dividendos. Es la convención de TradingView y la que usaba el Excel de Mecenas, así que los números son comparables con ambos. Ajustar también por dividendos correría el RSI entre 1 y 3 puntos.

**La banda es móvil, de 260 semanas.** No es el 70/30 clásico, porque cada acción tiene su propio rango: KO se mueve entre 25,8 y 80,5, RGTI entre 18,6 y 97,9, UNH entre 24,5 y 72,6. El 70/30 les queda mal a todas, por razones distintas.

## Para agregar o sacar una acción

Se edita `tickers.txt` y se hace commit. Nada más: la corrida siguiente baja el histórico completo de lo nuevo y le calcula los indicadores. El código no se toca.

Un ticker **con punto** (ej. `SMSN.UK`) se toma como mercado fuera de Estados Unidos y se busca en Stooq en vez de Tiingo.

## Si algo se rompe

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `CONFLICT` en `indicadores\` al hacer merge | El servidor y tú escribieron los mismos archivos | `python indicadores.py --generar`, `git add -A`, `git commit --no-edit`, `git push` |
| La carpeta local está atrasada | La tarea programada no se disparó | `git pull` a mano; revisar la tarea en el Programador de tareas |
| Una corrida en rojo en Actions | Ver el log del paso que falló | Los errores de cuota de Tiingo se resuelven solos en la corrida siguiente |
| Un ticker sin datos | Símbolo mal escrito o no cubierto | Queda anotado en `estado.json` y en el resumen del log; no rompe la corrida |
