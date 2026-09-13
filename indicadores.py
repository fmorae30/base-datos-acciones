#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Indicadores semanales sobre la base de precios diarios.

Calcula, para cada accion:
  - Velas semanales (agrupando los dias habiles de cada semana)
  - RSI de 14 periodos, metodo de Wilder, sobre precios ajustados solo por
    splits, que es la convencion de TradingView
  - Maximo y minimo del RSI en una ventana movil de 5 anios (260 semanas)
  - Posicion dentro de esa banda, de 0 a 100

La salida alimenta la hoja 3_Tecnico_ElliottRSI de Cartera_Mecenas.xlsx:
resumen_rsi.csv trae Ticker, RSI, RSI_min_5a y RSI_max_5a con esos nombres.

Para que sirve la banda movil: el 70/30 clasico es igual para todas las
acciones, pero cada papel tiene su propio rango. Hay acciones que rara vez
pasan de 65 y otras que se pasean sobre 80. Comparar el RSI de hoy contra
su propio rango de los ultimos 5 anios dice mas que compararlo contra 70.

  Posicion 100 = el RSI mas alto de los ultimos 5 anios
  Posicion   0 = el mas bajo
  Posicion  50 = justo en la mitad de su rango

Uso:
  python indicadores.py --generar        escribe la carpeta indicadores/
  python indicadores.py KO               ve una accion en pantalla
  python indicadores.py KO 30            ultimas 30 semanas
  python indicadores.py --todos          las 43 ordenadas por posicion

El workflow de GitHub corre "--generar" cada noche despues de actualizar los
precios, asi que los archivos de indicadores/ nunca quedan desfasados.

Sin dependencias: solo Python.
"""

import csv
import os
import sys
from datetime import date, datetime

RAIZ = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS = os.path.join(RAIZ, "data")
DIR_SALIDA = os.path.join(RAIZ, "indicadores")

PERIODO = 14           # periodos del RSI
VENTANA = 260          # 5 anios de semanas
MINIMO_VENTANA = 52    # bajo un anio de RSI, la banda no es representativa

CAMPOS_SERIE = ["Semana", "Open", "High", "Low", "Close", "Volume",
                "RSI", "RSI_max_5a", "RSI_min_5a", "Posicion", "Semanas_ventana"]


# --------------------------------------------------------------- lectura

def leer_diario(ruta):
    """Precios ajustados SOLO por splits, que es la convencion de TradingView.

    No se usan las columnas Adj* del CSV porque esas vienen ajustadas tambien
    por dividendos (metodologia CRSP), y eso corre el RSI entre 1 y 3 puntos
    respecto de lo que muestra cualquier plataforma de graficos. Para retorno
    total el ajuste por dividendos es lo correcto; para leer un indicador
    tecnico y poder contrastarlo contra TradingView, no.
    """
    filas = []
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                filas.append({
                    "fecha": datetime.strptime(r["Date"], "%Y-%m-%d").date(),
                    "open": float(r["Open"]),
                    "high": float(r["High"]),
                    "low": float(r["Low"]),
                    "close": float(r["Close"]),
                    "volumen": float(r["Volume"] or 0),
                    "split": float(r["SplitFactor"] or 1),
                })
            except (ValueError, KeyError):
                continue
    filas.sort(key=lambda x: x["fecha"])
    return ajustar_por_splits(filas)


def ajustar_por_splits(filas):
    """
    El precio de cada dia se divide por los splits que vinieron DESPUES.

    Sin esto, el 3x1 de TSLA de agosto de 2022 aparece como una caida de 67%
    en una semana y hunde el RSI durante meses. El volumen se corrige al
    reves, multiplicando, porque tras un split se transan mas acciones.
    """
    factor = 1.0
    for r in reversed(filas):
        if factor != 1.0:
            for c in ("open", "high", "low", "close"):
                r[c] /= factor
            r["volumen"] *= factor
        factor *= r["split"]
    return filas


def a_semanal(diarias):
    """Agrupa por semana ISO. La vela lleva la fecha del ultimo dia operado."""
    semanas, actual, clave_actual = [], None, None
    for d in diarias:
        clave = d["fecha"].isocalendar()[:2]
        if clave != clave_actual:
            if actual:
                semanas.append(actual)
            clave_actual = clave
            actual = {"fecha": d["fecha"], "open": d["open"], "high": d["high"],
                      "low": d["low"], "close": d["close"],
                      "volumen": d["volumen"], "dias": 1}
        else:
            actual["high"] = max(actual["high"], d["high"])
            actual["low"] = min(actual["low"], d["low"])
            actual["close"] = d["close"]
            actual["fecha"] = d["fecha"]
            actual["volumen"] += d["volumen"]
            actual["dias"] += 1
    if actual:
        semanas.append(actual)
    return semanas


# -------------------------------------------------------------------- RSI

def rsi_wilder(cierres, periodo=PERIODO):
    """RSI de Wilder. None donde aun no hay historia suficiente."""
    n = len(cierres)
    salida = [None] * n
    if n <= periodo:
        return salida

    subidas, bajadas = [], []
    for i in range(1, n):
        cambio = cierres[i] - cierres[i - 1]
        subidas.append(max(cambio, 0.0))
        bajadas.append(max(-cambio, 0.0))

    ps = sum(subidas[:periodo]) / periodo
    pb = sum(bajadas[:periodo]) / periodo
    salida[periodo] = _rsi(ps, pb)
    for i in range(periodo, len(subidas)):
        ps = (ps * (periodo - 1) + subidas[i]) / periodo
        pb = (pb * (periodo - 1) + bajadas[i]) / periodo
        salida[i + 1] = _rsi(ps, pb)
    return salida


def _rsi(ps, pb):
    if pb == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ps / pb))


def banda_movil(valores, ventana=VENTANA):
    """
    Maximo y minimo del RSI en las ultimas 'ventana' semanas, incluida la
    actual. Devuelve listas de (maximo, minimo, fecha_max, fecha_min, cuantas).
    Se recorre con una ventana simple: son pocas semanas y se ejecuta una vez
    al dia, asi que la claridad vale mas que la optimizacion.
    """
    salida = []
    for i in range(len(valores)):
        desde = max(0, i - ventana + 1)
        trozo = [(v, j) for j, v in enumerate(valores[desde:i + 1], start=desde)
                 if v is not None]
        if not trozo:
            salida.append((None, None, None, None, 0))
            continue
        vmax, imax = max(trozo)
        vmin, imin = min(trozo)
        salida.append((vmax, vmin, imax, imin, len(trozo)))
    return salida


def posicion(rsi, vmax, vmin):
    """Donde cae el RSI dentro de su banda: 0 el piso, 100 el techo."""
    if rsi is None or vmax is None or vmax == vmin:
        return None
    return (rsi - vmin) / (vmax - vmin) * 100.0


def alcance(semanas_ventana):
    """Como nombrar la banda: solo son '5 anios' si la ventana esta completa."""
    if semanas_ventana >= VENTANA:
        return "5 anios"
    return "%d semanas" % semanas_ventana


def lectura(pos, semanas_ventana):
    if pos is None:
        return ""
    if semanas_ventana < MINIMO_VENTANA:
        return "historia corta"
    if pos >= 90:
        return "techo de " + alcance(semanas_ventana)
    if pos <= 10:
        return "piso de " + alcance(semanas_ventana)
    if pos >= 75:
        return "parte alta"
    if pos <= 25:
        return "parte baja"
    return ""


# ------------------------------------------------------------------ motor

def analizar(ticker):
    """Devuelve las velas semanales con RSI, banda movil y posicion."""
    ruta = os.path.join(DIR_DATOS, ticker.upper() + ".csv")
    if not os.path.exists(ruta):
        raise SystemExit("No existe %s" % ruta)

    semanas = a_semanal(leer_diario(ruta))
    valores = rsi_wilder([s["close"] for s in semanas])
    bandas = banda_movil(valores)

    for i, s in enumerate(semanas):
        vmax, vmin, imax, imin, cuantas = bandas[i]
        s["rsi"] = valores[i]
        s["max"] = vmax
        s["min"] = vmin
        s["fecha_max"] = semanas[imax]["fecha"] if imax is not None else None
        s["fecha_min"] = semanas[imin]["fecha"] if imin is not None else None
        s["ventana"] = cuantas
        s["pos"] = posicion(valores[i], vmax, vmin)
    return semanas


def tickers_disponibles():
    if not os.path.isdir(DIR_DATOS):
        raise SystemExit("No existe la carpeta %s" % DIR_DATOS)
    return sorted(f[:-4] for f in os.listdir(DIR_DATOS) if f.endswith(".csv"))


# ---------------------------------------------------------------- generar

def generar():
    """Escribe indicadores/: una serie por accion y un resumen del ultimo dato."""
    dir_series = os.path.join(DIR_SALIDA, "semanal")
    os.makedirs(dir_series, exist_ok=True)

    resumen, fallidos = [], []
    for t in tickers_disponibles():
        try:
            semanas = analizar(t)
        except Exception as e:
            fallidos.append("%s: %s" % (t, e))
            continue
        if not semanas:
            fallidos.append("%s: sin velas" % t)
            continue

        with open(os.path.join(dir_series, t + ".csv"), "w",
                  encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(CAMPOS_SERIE)
            for s in semanas:
                w.writerow([
                    s["fecha"], r4(s["open"]), r4(s["high"]), r4(s["low"]),
                    r4(s["close"]), int(s["volumen"]),
                    r2(s["rsi"]), r2(s["max"]), r2(s["min"]), r2(s["pos"]),
                    s["ventana"],
                ])

        u = semanas[-1]
        resumen.append({
            "Ticker": t, "Semana": u["fecha"], "Close": r4(u["close"]),
            "RSI": r2(u["rsi"]), "RSI_max_5a": r2(u["max"]),
            "Fecha_max": u["fecha_max"] or "", "RSI_min_5a": r2(u["min"]),
            "Fecha_min": u["fecha_min"] or "", "Posicion": r2(u["pos"]),
            "Semanas_ventana": u["ventana"], "Semanas_totales": len(semanas),
            "Lectura": lectura(u["pos"], u["ventana"]),
        })

    resumen.sort(key=lambda r: (r["Posicion"] is None, r["Posicion"]))
    campos = list(resumen[0].keys()) if resumen else []
    with open(os.path.join(DIR_SALIDA, "resumen_rsi.csv"), "w",
              encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(resumen)

    print("Indicadores generados: %d acciones" % len(resumen))
    print("  %s" % os.path.join(DIR_SALIDA, "resumen_rsi.csv"))
    print("  %s  (una serie por accion)" % dir_series)
    for e in fallidos:
        print("  problema -> %s" % e)
    return 0 if resumen else 1


def r2(v):
    return "" if v is None else round(v, 2)


def r4(v):
    return "" if v is None else round(v, 4)


# ----------------------------------------------------------------- ver

def ver(ticker, cuantas=15):
    semanas = analizar(ticker)
    if not semanas:
        raise SystemExit("Sin datos para %s" % ticker)

    en_curso = semanas[-1]["fecha"].isocalendar()[:2] == date.today().isocalendar()[:2]
    u = semanas[-1]

    print("\n%s  ·  RSI semanal de %d periodos  ·  %d semanas de historia"
          % (ticker.upper(), PERIODO, len(semanas)))
    print("Banda movil de 5 anios  ·  precios ajustados por splits y dividendos\n")
    print("  Semana al     Cierre      RSI   Posicion  ")
    print("  " + "-" * 52)
    for s in semanas[-cuantas:]:
        marca = ""
        if s is u and en_curso:
            marca = "  (semana en curso, %d dia%s)" % (
                s["dias"], "" if s["dias"] == 1 else "s")
        print("  %s  %9.2f  %7s  %7s  %-18s%s"
              % (s["fecha"], s["close"], fmt(s["rsi"]), fmt(s["pos"]),
                 lectura(s["pos"], s["ventana"]), marca))

    if u["rsi"] is not None:
        etiqueta = alcance(u["ventana"])
        print("\n  RSI actual .......... %.2f" % u["rsi"])
        print("  Techo de %-11s %.2f   (%s)" % (etiqueta, u["max"], u["fecha_max"]))
        print("  Piso de %-12s %.2f   (%s)" % (etiqueta, u["min"], u["fecha_min"]))
        print("  Posicion en la banda  %.0f de 100%s"
              % (u["pos"], "   →  " + lectura(u["pos"], u["ventana"])
                 if lectura(u["pos"], u["ventana"]) else ""))
        print("  Ventana usada ....... %d semanas de %d" % (u["ventana"], VENTANA))
        if u["ventana"] < MINIMO_VENTANA:
            print("  Ojo: menos de un anio de RSI, la banda todavia no es confiable.")
    if en_curso:
        print("  Ojo: la ultima semana aun no cierra, su RSI puede moverse.")


def fmt(v):
    return "   -" if v is None else "%.2f" % v


def todos():
    filas = []
    for t in tickers_disponibles():
        try:
            u = analizar(t)[-1]
        except Exception:
            continue
        if u["pos"] is not None:
            filas.append((u["pos"], t, u["close"], u["rsi"], u["min"], u["max"],
                          u["ventana"]))
    filas.sort()

    print("\nRSI semanal y posicion en su banda de 5 anios  ·  %d acciones"
          % len(filas))
    print("Ordenadas de mas deprimidas a mas estiradas\n")
    print("  Ticker     Cierre      RSI   Banda 5 anios   Posicion")
    print("  " + "-" * 66)
    for pos, t, close, rsi, vmin, vmax, vent in filas:
        print("  %-8s %9.2f  %7.2f   %5.1f a %5.1f    %5.0f  %s"
              % (t, close, rsi, vmin, vmax, pos, lectura(pos, vent)))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--generar" in sys.argv:
        sys.exit(generar())
    elif "--todos" in sys.argv:
        todos()
    elif args:
        ver(args[0], int(args[1]) if len(args) > 1 else 15)
    else:
        raise SystemExit(__doc__)
