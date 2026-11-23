#!/usr/bin/env python3
"""Servidor local del editor de guion. Sirve la carpeta y guarda el proyecto en disco.

Uso:  python3 servidor.py        (abre http://127.0.0.1:8765)
Archivos que escribe: proyecto.json (datos), proyecto.bak.json (versión anterior), guion.md (guion legible).
"""
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import webbrowser

DIR = os.path.dirname(os.path.abspath(__file__))
PUERTO = int(os.environ.get("PUERTO", "8765"))
PROYECTO = os.path.join(DIR, "proyecto.json")
BACKUP = os.path.join(DIR, "proyecto.bak.json")
GUION = os.path.join(DIR, "guion.md")
MAX_BYTES = 5 * 1024 * 1024


def escribir_atomico(ruta, texto):
    fd, tmp = tempfile.mkstemp(dir=DIR, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, ruta)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIR, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, codigo, obj):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/proyecto":
            if not os.path.exists(PROYECTO):
                return self._json(404, {"error": "sin proyecto"})
            with open(PROYECTO, "r", encoding="utf-8") as f:
                return self._json(200, json.load(f))
        return super().do_GET()

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/proyecto":
            return self._json(404, {"error": "no existe"})
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > MAX_BYTES:
            return self._json(413, {"error": "tamaño inválido"})
        try:
            datos = json.loads(self.rfile.read(n).decode("utf-8"))
            proyecto = datos["proyecto"]
            markdown = datos.get("markdown", "")
        except Exception as e:
            return self._json(400, {"error": f"JSON inválido: {e}"})
        if os.path.exists(PROYECTO):
            shutil.copyfile(PROYECTO, BACKUP)
        escribir_atomico(PROYECTO, json.dumps(proyecto, ensure_ascii=False, indent=2))
        if markdown:
            escribir_atomico(GUION, markdown)
        self._json(200, {"ok": True})

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            return
        super().log_message(fmt, *args)


if __name__ == "__main__":
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", PUERTO), Handler)
    except OSError as e:
        sys.exit(f"No pude abrir el puerto {PUERTO}: {e}")
    url = f"http://127.0.0.1:{PUERTO}/"
    print(f"Editor en {url}  (Ctrl+C para cortar)")
    if "--no-abrir" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nChau.")
