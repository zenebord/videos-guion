#!/usr/bin/env python3
"""Servidor local del editor de guiones. Sirve la carpeta y guarda todo en disco.

Uso:  python3 servidor.py        (abre http://127.0.0.1:8765)

Estructura que mantiene:
  biblioteca/canciones.json        lista de canciones
  biblioteca/<id>-<nombre>.<ext>   los audios
  proyectos/<id>.json              un proyecto (guion) por archivo
  proyectos/<id>.md                el guion legible
  proyectos/index.json             resumen de proyectos (lo lee la versión estática en GitHub Pages)
"""
import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unicodedata
import uuid
import webbrowser
from urllib.parse import parse_qs, urlparse, unquote

DIR = os.path.dirname(os.path.abspath(__file__))
PUERTO = int(os.environ.get("PUERTO", "8765"))
BIBLIO = os.path.join(DIR, "biblioteca")
PROYS = os.path.join(DIR, "proyectos")
CANCIONES = os.path.join(BIBLIO, "canciones.json")
INDEX = os.path.join(PROYS, "index.json")
MAX_JSON = 5 * 1024 * 1024
MAX_AUDIO = 200 * 1024 * 1024
EXT_OK = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac", ".mpeg", ".mpga", ".webm", ".mp4"}
RE_ID = re.compile(r"^[a-z0-9]{3,16}$")
LOCK = threading.Lock()


def escribir_atomico(ruta, datos, binario=False):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb" if binario else "w", **({} if binario else {"encoding": "utf-8"})) as f:
            f.write(datos)
        os.replace(tmp, ruta)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def leer_json(ruta, defecto):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def guardar_json(ruta, obj):
    escribir_atomico(ruta, json.dumps(obj, ensure_ascii=False, indent=2))


def resumen(p):
    return {
        "id": p.get("id"),
        "nombre": p.get("nombre", ""),
        "cancionId": p.get("cancionId"),
        "etapas": len(p.get("marcadores", [])),
        "escenas": len(p.get("escenas", [])),
        "creado": p.get("creado", 0),
        "modificado": p.get("modificado", 0),
    }


def listar_proyectos():
    """Escanea proyectos/*.json: así el índice nunca queda desfasado."""
    out = []
    if os.path.isdir(PROYS):
        for n in sorted(os.listdir(PROYS)):
            if n.endswith(".json") and not n.endswith(".bak.json") and n != "index.json":
                p = leer_json(os.path.join(PROYS, n), None)
                if isinstance(p, dict) and p.get("id"):
                    out.append(resumen(p))
    return out


def refrescar_index():
    os.makedirs(PROYS, exist_ok=True)
    guardar_json(INDEX, listar_proyectos())


def slug(texto):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "audio"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIR, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # --- utilidades ---
    def _json(self, codigo, obj):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _origen_ok(self):
        """Defensa contra páginas ajenas que le peguen a localhost (CSRF / DNS rebinding)."""
        host = self.headers.get("Host", "").lower()
        if host not in (f"127.0.0.1:{PUERTO}", f"localhost:{PUERTO}"):
            return False
        origen = self.headers.get("Origin")
        return origen is None or origen in (f"http://127.0.0.1:{PUERTO}", f"http://localhost:{PUERTO}")

    def _cuerpo_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > MAX_JSON:
            raise ValueError("tamaño inválido")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _ruta(self):
        return [p for p in urlparse(self.path).path.split("/") if p]

    # --- GET ---
    def do_GET(self):
        r = self._ruta()
        if r[:1] != ["api"]:
            return super().do_GET()
        if not self._origen_ok():
            return self._json(403, {"error": "origen no permitido"})
        if r == ["api", "canciones"]:
            return self._json(200, leer_json(CANCIONES, []))
        if r == ["api", "proyectos"]:
            return self._json(200, listar_proyectos())
        if len(r) == 3 and r[1] == "proyectos" and RE_ID.match(r[2]):
            p = leer_json(os.path.join(PROYS, r[2] + ".json"), None)
            return self._json(200, p) if p else self._json(404, {"error": "no existe"})
        self._json(404, {"error": "no existe"})

    # --- POST: subir canción ---
    def do_POST(self):
        r = self._ruta()
        if r != ["api", "canciones"]:
            return self._json(404, {"error": "no existe"})
        if not self._origen_ok():
            return self._json(403, {"error": "origen no permitido"})
        q = parse_qs(urlparse(self.path).query)
        nombre_arch = unquote((q.get("nombre") or [""])[0])
        ext = os.path.splitext(nombre_arch)[1].lower()
        if ext not in EXT_OK:
            return self._json(415, {"error": f"formato no admitido ({ext or 'sin extensión'})"})
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > MAX_AUDIO:
            return self._json(413, {"error": "tamaño inválido"})
        try:
            duracion = float((q.get("duracion") or ["0"])[0])
        except ValueError:
            duracion = 0.0
        cid = uuid.uuid4().hex[:8]
        stem = os.path.splitext(os.path.basename(nombre_arch))[0]
        archivo = f"{cid}-{slug(stem)}{ext}"
        os.makedirs(BIBLIO, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=BIBLIO, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                resto = n
                while resto > 0:
                    trozo = self.rfile.read(min(1 << 20, resto))
                    if not trozo:
                        raise IOError("conexión cortada")
                    f.write(trozo)
                    resto -= len(trozo)
            os.replace(tmp, os.path.join(BIBLIO, archivo))
        except Exception as e:
            if os.path.exists(tmp):
                os.unlink(tmp)
            return self._json(500, {"error": str(e)})
        cancion = {"id": cid, "nombre": stem.strip() or "Sin nombre", "archivo": archivo,
                   "duracion": duracion, "bytes": n, "creado": int(__import__("time").time() * 1000)}
        with LOCK:
            lista = leer_json(CANCIONES, [])
            lista.append(cancion)
            guardar_json(CANCIONES, lista)
        self._json(200, cancion)

    # --- PUT: guardar proyecto (upsert) o renombrar canción ---
    def do_PUT(self):
        r = self._ruta()
        if not self._origen_ok():
            return self._json(403, {"error": "origen no permitido"})
        try:
            if len(r) == 3 and r[1] == "proyectos" and r[0] == "api" and RE_ID.match(r[2]):
                datos = self._cuerpo_json()
                p, md = datos["proyecto"], datos.get("markdown", "")
                if not isinstance(p, dict) or not isinstance(p.get("marcadores"), list):
                    raise ValueError("proyecto inválido")
                p["id"] = r[2]
                os.makedirs(PROYS, exist_ok=True)
                ruta = os.path.join(PROYS, r[2] + ".json")
                with LOCK:
                    if os.path.exists(ruta):
                        shutil.copyfile(ruta, os.path.join(PROYS, r[2] + ".bak.json"))
                    guardar_json(ruta, p)
                    if md:
                        escribir_atomico(os.path.join(PROYS, r[2] + ".md"), md)
                    refrescar_index()
                return self._json(200, {"ok": True})
            if len(r) == 3 and r[1] == "canciones" and r[0] == "api" and RE_ID.match(r[2]):
                nombre = str(self._cuerpo_json().get("nombre", "")).strip()
                if not nombre:
                    raise ValueError("nombre vacío")
                with LOCK:
                    lista = leer_json(CANCIONES, [])
                    c = next((x for x in lista if x["id"] == r[2]), None)
                    if not c:
                        return self._json(404, {"error": "no existe"})
                    c["nombre"] = nombre
                    guardar_json(CANCIONES, lista)
                return self._json(200, c)
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"error": f"datos inválidos: {e}"})
        self._json(404, {"error": "no existe"})

    # --- DELETE ---
    def do_DELETE(self):
        r = self._ruta()
        if not self._origen_ok():
            return self._json(403, {"error": "origen no permitido"})
        if len(r) == 3 and r[0] == "api" and RE_ID.match(r[2]):
            with LOCK:
                if r[1] == "proyectos":
                    for ext in (".json", ".md", ".bak.json"):
                        try:
                            os.unlink(os.path.join(PROYS, r[2] + ext))
                        except FileNotFoundError:
                            pass
                    refrescar_index()
                    return self._json(200, {"ok": True})
                if r[1] == "canciones":
                    usos = [p["nombre"] for p in listar_proyectos() if p["cancionId"] == r[2]]
                    if usos:
                        return self._json(409, {"error": "la canción está en uso", "proyectos": usos})
                    lista = leer_json(CANCIONES, [])
                    c = next((x for x in lista if x["id"] == r[2]), None)
                    if not c:
                        return self._json(404, {"error": "no existe"})
                    try:
                        os.unlink(os.path.join(BIBLIO, os.path.basename(c["archivo"])))
                    except FileNotFoundError:
                        pass
                    guardar_json(CANCIONES, [x for x in lista if x["id"] != r[2]])
                    return self._json(200, {"ok": True})
        self._json(404, {"error": "no existe"})

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            return
        super().log_message(fmt, *args)


if __name__ == "__main__":
    os.makedirs(BIBLIO, exist_ok=True)
    os.makedirs(PROYS, exist_ok=True)
    refrescar_index()
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
