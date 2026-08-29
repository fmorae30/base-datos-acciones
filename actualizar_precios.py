#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Actualiza la base de datos historica de precios diarios.

Fuentes:
  - Tiingo   -> tickers de EE.UU. (los que NO llevan punto en tickers.txt)
  - Stooq    -> tickers con punto (ej. SMSN.UK), mercados fuera de EE.UU.

Comportamiento:
  - Si el CSV del ticker no existe, baja el historico completo.
  - Si ya existe, baja solo los ultimos dias y los mezcla (re-pide 10 dias
    hacia atras para capturar correcciones de la fuente).
  - Si detecta un split nuevo, vuelve a bajar el historico completo de ese
    ticker, porque las columnas ajustadas cambian hacia atras.

Limites: el plan gratis de Tiingo permite 50 requests por hora. El script
corta la corrida al llegar a MAX_TIINGO (45 por defecto) y guarda en que
quedo; la siguiente corrida sigue por los tickers mas atrasados.

Variables de entorno:
  TIINGO_TOKEN    (obligatorio para tickers de EE.UU.)
  MAX_TIINGO      tope de requests a Tiingo por corrida (default 45)
  FULL_REFRESH    "1" para rebajar todo el historico desde cero
  DATA_DIR        carpeta de salida (default "data")
  ESPERAR_LIMITE  "1" para que espere solo cuando se agota la cuota horaria
  MINUTOS_ESPERA  cuanto espera cada vez (default 10)
  MAX_ESPERAS     cuantas esperas tolera antes de rendirse (default 12)

Uso:
  python actualizar_precios.py            # corrida normal
  python actualizar_precios.py KO MCD     # fuerza solo esos tickers
"""

import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(RAIZ, os.environ.get("DATA_DIR", "data"))
ARCHIVO_TICKERS = os.path.join(RAIZ, "tickers.txt")
ARCHIVO_ESTADO = os.path.join(RAIZ, "estado.json")

TOKEN = os.environ.get("TIINGO_TOKEN", "").strip()
MAX_TIINGO = int(os.environ.get("MAX_TIINGO", "45"))
FULL_REFRESH = os.environ.get("FULL_REFRESH", "").strip().lower() in ("1", "true", "si", "yes")

ESPERAR_LIMITE = os.environ.get("ESPERAR_LIMITE", "").strip().lower() in ("1", "true", "si", "yes")
MINUTOS_ESPERA = int(os.environ.get("MINUTOS_ESPERA", "10"))
MAX_ESPERAS = int(os.environ.get("MAX_ESPERAS", "12"))

INICIO_HISTORIA = "1900-01-01"   # Tiingo sin startDate devuelve SOLO el ultimo dia
DIAS_SOLAPE = 10          # dias que se vuelven a pedir en cada actualizacion
PAUSA_TIINGO = 1.0        # segundos entre requests
PAUSA_STOOQ = 2.0

CAMPOS = [
    "Date", "Open", "High", "Low", "Close", "Volume",
    "AdjOpen", "AdjHigh", "AdjLow", "AdjClose", "AdjVolume",
    "Dividend", "SplitFactor",
]

HOY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


class LimiteAlcanzado(Exception):
    """La fuente respondio 429: se corta la corrida."""


class SinDatos(Exception):
    """La fuente no tiene datos para ese ticker."""


# ---------------------------------------------------------------- utilidades

def log(msg):
    print(msg, flush=True)


def leer_tickers():
    """Un ticker por linea; todo lo que viene despues de # es comentario."""
    tickers, vistos = [], set()
    with open(ARCHIVO_TICKERS, "r", encoding="utf-8") as f:
        for linea in f:
            simbolo = linea.split("#", 1)[0].strip().upper()
            if simbolo and simbolo not in vistos:
                vistos.add(simbolo)
                tickers.append(simbolo)
    return tickers


def cargar_estado():
    if os.path.exists(ARCHIVO_ESTADO):
        try:
            with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            log("  aviso: estado.json ilegible, se reconstruye")
    return {"tickers": {}}


def guardar_estado(estado):
    estado["ultima_corrida"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tmp = ARCHIVO_ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, ARCHIVO_ESTADO)


def bajar(url, reintentos=3):
    """GET simple. Lanza LimiteAlcanzado en 429."""
    ultimo_error = None
    for intento in range(reintentos):
        req = urllib.request.Request(url, headers={"User-Agent": "base-datos-acciones/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise LimiteAlcanzado(url.split("?")[0])
            if e.code == 404:
                raise SinDatos("404")
            ultimo_error = "HTTP %s" % e.code
        except Exception as e:  # timeouts, DNS, conexion cortada
            ultimo_error = str(e)
        time.sleep(2 * (intento + 1))
    raise RuntimeError(ultimo_error or "fallo desconocido")


def a_texto(valor):
    """Normaliza numeros: 12.0 -> 12, y deja vacio lo que venga vacio."""
    v = (valor or "").strip()
    if v in ("", "N/A", "null", "None"):
        return ""
    if v.endswith(".0"):
        v = v[:-2]
    return v


# ------------------------------------------------------------------- fuentes

def desde_tiingo(ticker, desde=None):
    if not TOKEN:
        raise RuntimeError("falta TIINGO_TOKEN")
    url = ("https://api.tiingo.com/tiingo/daily/%s/prices?format=csv&token=%s"
           % (urllib.parse.quote(ticker), TOKEN))
    if desde:
        url += "&startDate=%s" % desde
    texto = bajar(url)
    bajo = texto.lstrip().lower()
    # Tiingo avisa la cuota agotada dentro del cuerpo, con HTTP 200.
    if "request allocation" in bajo or "run over your" in bajo:
        raise LimiteAlcanzado("cuota de Tiingo agotada")
    if not texto.strip() or texto.strip().startswith("["):
        raise SinDatos("respuesta vacia")
    if bajo.startswith("error") or bajo.startswith("{\"detail"):
        raise RuntimeError(texto.strip()[:120])

    filas = []
    for r in csv.DictReader(io.StringIO(texto)):
        fecha = (r.get("date") or "")[:10]
        if not fecha:
            continue
        filas.append({
            "Date": fecha,
            "Open": a_texto(r.get("open")),
            "High": a_texto(r.get("high")),
            "Low": a_texto(r.get("low")),
            "Close": a_texto(r.get("close")),
            "Volume": a_texto(r.get("volume")),
            "AdjOpen": a_texto(r.get("adjOpen")),
            "AdjHigh": a_texto(r.get("adjHigh")),
            "AdjLow": a_texto(r.get("adjLow")),
            "AdjClose": a_texto(r.get("adjClose")),
            "AdjVolume": a_texto(r.get("adjVolume")),
            "Dividend": a_texto(r.get("divCash")) or "0",
            "SplitFactor": a_texto(r.get("splitFactor")) or "1",
        })
    if not filas:
        raise SinDatos("sin filas")
    return filas


def desde_stooq(ticker, desde=None):
    url = "https://stooq.com/q/d/l/?s=%s&i=d" % urllib.parse.quote(ticker.lower())
    if desde:
        url += "&d1=%s&d2=%s" % (desde.replace("-", ""),
                                 datetime.now(timezone.utc).strftime("%Y%m%d"))
    texto = bajar(url)
    cabecera = texto.strip().split("\n", 1)[0].lower()
    if "exceeded" in texto.lower() or "limit" in cabecera:
        raise LimiteAlcanzado("stooq")
    if not cabecera.startswith("date"):
        raise SinDatos(texto.strip()[:60] or "respuesta vacia")

    filas = []
    for r in csv.DictReader(io.StringIO(texto)):
        fecha = (r.get("Date") or "")[:10]
        if not fecha:
            continue
        o, h, l, c = (a_texto(r.get("Open")), a_texto(r.get("High")),
                      a_texto(r.get("Low")), a_texto(r.get("Close")))
        v = a_texto(r.get("Volume"))
        # Stooq entrega la serie ya ajustada: las columnas Adj* repiten el dato.
        filas.append({
            "Date": fecha, "Open": o, "High": h, "Low": l, "Close": c, "Volume": v,
            "AdjOpen": o, "AdjHigh": h, "AdjLow": l, "AdjClose": c, "AdjVolume": v,
            "Dividend": "0", "SplitFactor": "1",
        })
    if not filas:
        raise SinDatos("sin filas")
    return filas


def fuente_de(ticker):
    return "stooq" if "." in ticker else "tiingo"


# --------------------------------------------------------------------- disco

def ruta_csv(ticker):
    seguro = ticker.replace("/", "-").replace("\\", "-")
    return os.path.join(DATA_DIR, "%s.csv" % seguro)


def leer_csv(ticker):
    ruta = ruta_csv(ticker)
    if not os.path.exists(ruta):
        return {}
    filas = {}
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("Date"):
                filas[r["Date"]] = {c: (r.get(c) or "") for c in CAMPOS}
    return filas


def escribir_csv(ticker, filas):
    os.makedirs(DATA_DIR, exist_ok=True)
    ruta = ruta_csv(ticker)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        for fecha in sorted(filas):
            w.writerow(filas[fecha])
    os.replace(tmp, ruta)


# ------------------------------------------------------------------ un ticker

def procesar(ticker):
    """Devuelve (mensaje, requests_tiingo_usados, info_estado)."""
    fuente = fuente_de(ticker)
    existentes = {} if FULL_REFRESH else leer_csv(ticker)
    completo = not existentes

    desde = INICIO_HISTORIA
    if not completo:
        ultima = max(existentes)
        try:
            d = datetime.strptime(ultima, "%Y-%m-%d") - timedelta(days=DIAS_SOLAPE)
            desde = d.strftime("%Y-%m-%d")
        except ValueError:
            completo, existentes, desde = True, {}, INICIO_HISTORIA

    traer = desde_tiingo if fuente == "tiingo" else desde_stooq
    nuevas = traer(ticker, desde)
    usados = 1

    # Split nuevo => el historico ajustado cambia hacia atras: rebajar todo.
    if not completo and fuente == "tiingo":
        def es_split_nuevo(f):
            sf = (f.get("SplitFactor") or "1").strip()
            if sf in ("", "1", "1.0"):
                return False
            previo = existentes.get(f["Date"], {}).get("SplitFactor", "")
            return previo.strip() != sf     # split que todavia no estaba guardado

        if any(es_split_nuevo(f) for f in nuevas):
            log("    split detectado -> rebajando historico completo")
            nuevas = desde_tiingo(ticker, INICIO_HISTORIA)
            usados += 1
            existentes, completo = {}, True

    antes = len(existentes)
    for f in nuevas:
        existentes[f["Date"]] = f
    escribir_csv(ticker, existentes)

    agregadas = len(existentes) - antes
    ultima = max(existentes)
    info = {
        "fuente": fuente,
        "ultima_revision": HOY,
        "ultima_fecha": ultima,
        "filas": len(existentes),
        "error": "",
    }
    modo = "historico completo" if completo else "actualizacion"
    aviso = "  <-- OJO: muy pocas filas para un historico" if completo and len(existentes) < 20 else ""
    return ("%s: %s, %s filas nuevas (total %d, hasta %s)%s"
            % (ticker, modo, agregadas, len(existentes), ultima, aviso)), usados, info


# ---------------------------------------------------------------------- main

def main():
    forzados = [t.upper() for t in sys.argv[1:]]
    tickers = leer_tickers()
    if forzados:
        tickers = [t for t in tickers if t in forzados] or forzados

    estado = cargar_estado()
    por_ticker = estado.setdefault("tickers", {})

    # Pendientes = los que no se revisaron hoy, empezando por los mas atrasados.
    def antiguedad(t):
        return por_ticker.get(t, {}).get("ultima_revision", "0000-00-00")

    def esta_pendiente(t):
        info = por_ticker.get(t, {})
        # Un ticker que fallo se reintenta aunque ya se haya "revisado" hoy.
        return info.get("ultima_revision") != HOY or bool(info.get("error"))

    if forzados or FULL_REFRESH:
        pendientes = list(tickers)
    else:
        pendientes = sorted([t for t in tickers if esta_pendiente(t)], key=antiguedad)

    log("Tickers en la lista: %d | pendientes hoy: %d | tope Tiingo: %d"
        % (len(tickers), len(pendientes), MAX_TIINGO))
    if FULL_REFRESH:
        log("FULL_REFRESH activo: se rebaja todo el historico.")

    usados = 0
    ok = fallidos = 0
    errores = []
    cortado = False

    esperas = 0

    for ticker in pendientes:
        es_tiingo = fuente_de(ticker) == "tiingo"
        if es_tiingo and usados >= MAX_TIINGO:
            log("Tope de requests alcanzado; el resto queda para la proxima corrida.")
            cortado = True
            break

        while True:      # se repite solo si hay que esperar a que vuelva la cuota
            try:
                msg, gastados, info = procesar(ticker)
                usados += gastados if es_tiingo else 0
                por_ticker[ticker] = info
                ok += 1
                log("  " + msg)
            except LimiteAlcanzado as e:
                if ESPERAR_LIMITE and esperas < MAX_ESPERAS:
                    esperas += 1
                    log("  cuota agotada (%s). Esperando %d min y retomo en %s "
                        "[espera %d de %d]" % (e, MINUTOS_ESPERA, ticker, esperas, MAX_ESPERAS))
                    guardar_estado(estado)      # el avance queda en disco por si se corta
                    time.sleep(MINUTOS_ESPERA * 60)
                    usados = 0                  # la ventana horaria se libera
                    continue                    # reintenta el MISMO ticker
                log("Cuota de la fuente agotada (%s). Se guarda el avance y se corta." % e)
                log("Consejo: relanza con ESPERAR_LIMITE=1 para que espere solo.")
                cortado = True
            except SinDatos as e:
                usados += 1 if es_tiingo else 0
                fallidos += 1
                errores.append("%s: sin datos (%s)" % (ticker, e))
                info = por_ticker.get(ticker, {"fuente": fuente_de(ticker)})
                # sin datos es permanente: se marca revisado para no gastar mas requests hoy
                info.update({"ultima_revision": HOY, "error": "", "sin_datos": str(e)})
                por_ticker[ticker] = info
                log("  %s: SIN DATOS (%s)" % (ticker, e))
            except Exception as e:
                usados += 1 if es_tiingo else 0
                fallidos += 1
                errores.append("%s: %s" % (ticker, e))
                info = por_ticker.get(ticker, {"fuente": fuente_de(ticker)})
                # error transitorio: queda con error, se reintenta en la proxima corrida
                info.update({"ultima_revision": HOY, "error": str(e)[:200]})
                por_ticker[ticker] = info
                log("  %s: ERROR %s" % (ticker, e))
            break

        if cortado:
            break
        time.sleep(PAUSA_TIINGO if es_tiingo else PAUSA_STOOQ)

    guardar_estado(estado)

    quedan = len([t for t in tickers if esta_pendiente(t)])
    log("")
    log("Resumen: %d actualizados, %d con problemas, %d requests a Tiingo, %d pendientes."
        % (ok, fallidos, usados, quedan))
    for e in errores:
        log("  - " + e)
    if cortado and quedan:
        log("Quedaron tickers pendientes: la proxima corrida programada los toma.")
    # Fallar solo si no se pudo actualizar nada teniendo cosas que hacer.
    if ok == 0 and pendientes and not cortado:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
