#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prueba si un ticker existe en Tiingo o en Stooq, antes de agregarlo a
tickers.txt. No toca la base: solo consulta y muestra el resultado.

  set TIINGO_TOKEN=tu-token
  python probar_tickers.py                 prueba la lista de abajo
  python probar_tickers.py DAL SINGY       prueba solo esos

Regla de ruteo, la misma del pipeline: sin punto va a Tiingo, con punto va
a Stooq. Los simbolos con punto de este listado son candidatos para mercados
que Tiingo no cubre.

Ojo con el consumo: cada consulta a Tiingo gasta una de las 50 por hora del
plan gratis, asi que conviene correrlo lejos de la hora de las corridas.
"""

import csv
import io
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TIINGO_TOKEN", "").strip()
PAUSA = 2.0

# (simbolo, que es). Sin punto -> Tiingo. Con punto -> Stooq.
CANDIDATOS = [
    # --- Controles: si estos fallan, el problema es la conexion o el token
    ("KO", "control Tiingo, deberia funcionar"),
    ("ko.us", "control Stooq, deberia funcionar"),

    # --- Delta Air Lines
    ("DAL", "Delta Air Lines, NYSE"),

    # --- Singapore Airlines
    ("SINGY", "Singapore Airlines, ADR no patrocinado OTC"),
    ("c6l.sg", "Singapore Airlines, accion principal en Singapur"),

    # --- Samsung Electronics
    ("SSNLF", "Samsung, ADR OTC (casi no transa)"),
    ("smsn.uk", "Samsung, GDR de Londres"),
    ("005930.kr", "Samsung, Korea Exchange"),
    ("005930.ks", "Samsung, otra variante KRX"),
    ("ssun.de", "Samsung, Frankfurt"),

    # --- Unitree Robotics (aunque haya datos, lleva menos de un mes cotizando)
    ("688836.cn", "Unitree, STAR Market Shanghai"),
    ("688836.ss", "Unitree, otra variante Shanghai"),

    # --- Iberdrola y Hermes, para reemplazar los ADR si hay algo mejor
    ("ibe.es", "Iberdrola, Madrid"),
    ("ibe.mc", "Iberdrola, otra variante Madrid"),
    ("rms.fr", "Hermes, Paris"),
    ("rms.pa", "Hermes, otra variante Paris"),
]


def bajar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def probar_tiingo(simbolo):
    if not TOKEN:
        return None, "falta TIINGO_TOKEN en el entorno"
    url = ("https://api.tiingo.com/tiingo/daily/%s/prices"
           "?format=csv&startDate=1900-01-01&token=%s"
           % (urllib.parse.quote(simbolo), TOKEN))
    try:
        texto = bajar(url)
    except urllib.error.HTTPError as e:
        return None, "no existe en Tiingo" if e.code == 404 else "HTTP %s" % e.code
    except Exception as e:
        return None, str(e)[:50]

    bajo = texto.lstrip().lower()
    if "request allocation" in bajo or "run over your" in bajo:
        return None, "cuota horaria de Tiingo agotada, reintenta en una hora"
    if not bajo.startswith("date"):
        return None, texto.strip()[:50] or "respuesta vacia"
    filas = [r for r in csv.DictReader(io.StringIO(texto)) if r.get("date")]
    return (filas, None) if filas else (None, "sin filas")


def probar_stooq(simbolo):
    url = "https://stooq.com/q/d/l/?s=%s&i=d" % urllib.parse.quote(simbolo.lower())
    try:
        texto = bajar(url)
    except Exception as e:
        return None, str(e)[:50]
    if "exceeded" in texto.lower():
        return None, "Stooq bloqueo la IP por exceso de consultas"
    if not texto.strip().lower().startswith("date"):
        return None, texto.strip()[:40] or "no existe en Stooq"
    filas = [r for r in csv.DictReader(io.StringIO(texto)) if r.get("Date")]
    return (filas, None) if filas else (None, "sin filas")


def campo(fila, *nombres):
    for n in nombres:
        if n in fila:
            return fila[n]
    return "?"


def main():
    pedidos = sys.argv[1:]
    lista = ([(s, "pedido en la linea de comandos") for s in pedidos]
             if pedidos else CANDIDATOS)

    if not TOKEN:
        print("Aviso: sin TIINGO_TOKEN solo se pueden probar los simbolos")
        print("con punto, que van a Stooq.\n")

    print("%-12s %-6s %-42s %s" % ("SIMBOLO", "FUENTE", "QUE ES", "RESULTADO"))
    print("-" * 110)

    for simbolo, desc in lista:
        stooq = "." in simbolo
        fuente = "Stooq" if stooq else "Tiingo"
        filas, error = (probar_stooq(simbolo) if stooq else probar_tiingo(simbolo))

        if error:
            print("%-12s %-6s %-42s NO  -- %s" % (simbolo, fuente, desc, error))
        else:
            ini = campo(filas[0], "Date", "date")[:10]
            fin = campo(filas[-1], "Date", "date")[:10]
            cierre = campo(filas[-1], "Close", "close")
            semanas = len(filas) // 5
            aviso = ""
            if semanas < 15:
                aviso = "  <-- muy poca historia, no alcanza para RSI semanal"
            print("%-12s %-6s %-42s SI  -- %d ruedas, %s a %s, cierre %s%s"
                  % (simbolo, fuente, desc, len(filas), ini, fin, cierre, aviso))
        time.sleep(PAUSA)

    print()
    print("Los que digan SI se agregan a tickers.txt tal cual, en MAYUSCULAS.")
    print("El punto es lo que decide la fuente, asi que respetalo.")


if __name__ == "__main__":
    main()
