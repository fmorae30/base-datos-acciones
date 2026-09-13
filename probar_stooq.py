#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prueba que simbolos de Stooq existen, antes de agregarlos a tickers.txt.

Stooq no publica su lista de mercados y bloquea el acceso automatizado desde
fuera, asi que la unica forma de saber si cubre Madrid, Paris o Corea es
preguntarle desde tu conexion. Eso hace este script: pide cada candidato y
reporta si trae datos, desde cuando y hasta cuando.

  python probar_stooq.py

No toca nada de la base. Solo consulta y muestra el resultado.
"""

import csv
import io
import time
import urllib.error
import urllib.parse
import urllib.request

# Controles: si estos dos fallan, el problema es la conexion, no el simbolo.
CONTROLES = [
    ("ko.us", "Coca-Cola (control, deberia funcionar)"),
    ("aapl.us", "Apple (control, deberia funcionar)"),
]

CANDIDATOS = [
    # Iberdrola — Bolsa de Madrid
    ("ibe.es", "Iberdrola, sufijo España"),
    ("ibe.mc", "Iberdrola, codigo Madrid"),
    ("ibe.sp", "Iberdrola, otra variante"),
    # Hermes — Euronext Paris
    ("rms.fr", "Hermes, sufijo Francia"),
    ("rms.pa", "Hermes, codigo Paris"),
    # Samsung Electronics — Korea Exchange y alternativas
    ("005930.kr", "Samsung, sufijo Corea"),
    ("005930.ks", "Samsung, codigo KRX"),
    ("smsn.uk", "Samsung GDR en Londres"),
    ("ssun.de", "Samsung en Frankfurt"),
    # De paso, los ADR que ya usamos, para comparar cobertura
    ("ibdry.us", "Iberdrola ADR (ya lo tenemos via Tiingo)"),
    ("hesay.us", "Hermes ADR (ya lo tenemos via Tiingo)"),
]

PAUSA = 2.0   # Stooq bloquea por IP si se le pide muy seguido


def probar(simbolo):
    url = "https://stooq.com/q/d/l/?s=%s&i=d" % urllib.parse.quote(simbolo)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            texto = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:
        return None, str(e)[:60]

    limpio = texto.strip()
    if "exceeded" in limpio.lower():
        return None, "Stooq bloqueo la IP por exceso de consultas"
    if not limpio.lower().startswith("date"):
        return None, limpio[:50] or "respuesta vacia"

    filas = [r for r in csv.DictReader(io.StringIO(texto)) if r.get("Date")]
    if not filas:
        return None, "sin filas"
    return filas, None


def main():
    print("Probando simbolos en Stooq. Esto toma un par de minutos.\n")
    for grupo, lista in (("CONTROLES", CONTROLES), ("CANDIDATOS", CANDIDATOS)):
        print("== %s" % grupo)
        for simbolo, desc in lista:
            filas, error = probar(simbolo)
            if error:
                print("  %-12s NO   %-42s %s" % (simbolo, desc, error))
            else:
                print("  %-12s SI   %-42s %d filas, %s a %s, ultimo cierre %s"
                      % (simbolo, desc, len(filas), filas[0]["Date"],
                         filas[-1]["Date"], filas[-1]["Close"]))
            time.sleep(PAUSA)
        print()

    print("Los que digan SI se pueden agregar a tickers.txt tal cual, en")
    print("mayusculas y con el punto: el script los manda a Stooq automaticamente.")


if __name__ == "__main__":
    main()
