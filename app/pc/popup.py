import argparse
import ctypes
import json
import os
import random
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BANCO_PATH = BASE_DIR / "data" / "banco.json"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
PROGRESO_PATH = Path(__file__).resolve().parent / "progreso.json"
UI_PATH = Path(__file__).resolve().parent / "popup_ui.html"


def cargar_json(ruta: Path, default: dict) -> dict:
    """Lee un archivo JSON de forma segura devolviendo default si falla."""
    if not ruta.exists():
        return default
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def guardar_json(ruta: Path, data: dict) -> None:
    """Guarda un diccionario como JSON legible."""
    ruta.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def encontrar_navegador() -> str | None:
    """Busca Microsoft Edge o Google Chrome en Windows para modo --app."""
    candidatos = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LocalAppData", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LocalAppData", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for ruta in candidatos:
        if ruta.exists():
            return str(ruta)
    return None


def obtener_pantalla() -> tuple[int, int]:
    """Obtiene el ancho y alto de la pantalla principal en Windows."""
    try:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


class EntrenadorState:
    """Estado compartido entre el temporizador y el servidor HTTP del pop-up."""

    def __init__(self) -> None:
        self.config = cargar_json(
            CONFIG_PATH,
            {"intervalo_minutos": 45, "preguntas_por_sesion": 2, "mostrar_al_iniciar": True},
        )
        self.progreso = cargar_json(PROGRESO_PATH, {})
        self.siguiente_disparo = 0.0
        self.lock = threading.Lock()
        self.evento_espera = threading.Event()
        self.ronda_actual: list[dict] = []

    def obtener_items(self) -> list[dict]:
        """Construye la lista unificada de vocabulario y frases desde data/banco.json."""
        banco = cargar_json(BANCO_PATH, {"vocabulario": [], "frases": []})
        items: list[dict] = []
        for v in banco.get("vocabulario", []):
            items.append(
                {
                    "id": v["id"],
                    "tipo": "Vocabulario",
                    "dia": v.get("dia", "?"),
                    "episodio": v.get("episodio", ""),
                    "pregunta": v["es"],
                    "respuesta": v["en"],
                    "extra": f"Ejemplo: {v.get('ejemplo', '')}" if v.get("ejemplo") else "",
                    "bloques": [],
                    "nivel": self.progreso.get(v["id"], 0),
                }
            )
        for f in banco.get("frases", []):
            items.append(
                {
                    "id": f["id"],
                    "tipo": f"Shadowing ({f.get('personaje', 'Friends')})",
                    "dia": f.get("dia", "?"),
                    "episodio": f.get("episodio", ""),
                    "pregunta": f["es"],
                    "respuesta": f["en"],
                    "extra": "",
                    "bloques": f.get("bloques", []),
                    "nivel": self.progreso.get(f["id"], 0),
                }
            )
        return items

    def preparar_ronda(self) -> list[dict]:
        """Elige N preguntas únicas ponderadas por menor nivel de dominio."""
        items = self.obtener_items()
        if not items:
            return []
        cantidad = min(int(self.config.get("preguntas_por_sesion", 2)), len(items))
        seleccionados: list[dict] = []
        pool = items[:]
        for _ in range(cantidad):
            pesos = [max(1, 6 - it["nivel"]) for it in pool]
            elegido = random.choices(pool, weights=pesos, k=1)[0]
            seleccionados.append(elegido)
            pool.remove(elegido)
        self.ronda_actual = seleccionados
        return seleccionados

    def calificar(self, item_id: str, delta: int) -> None:
        """Actualiza y persiste el nivel de dominio (0-5) de una tarjeta."""
        with self.lock:
            actual = self.progreso.get(item_id, 0)
            self.progreso[item_id] = max(0, min(5, actual + delta))
            guardar_json(PROGRESO_PATH, self.progreso)

    def programar(self, minutos: int | None = None) -> None:
        """Programa la próxima ronda en N minutos y despierta si hace falta."""
        mins = minutos if minutos is not None else int(self.config.get("intervalo_minutos", 45))
        with self.lock:
            self.siguiente_disparo = time.time() + max(1, mins) * 60
        self.evento_espera.set()


def crear_handler(state: EntrenadorState):
    """Crea el manejador HTTP para servir la UI moderna y las acciones del pop-up."""

    class PopupHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/index"):
                html = UI_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif self.path == "/api/ronda":
                self._json(
                    200,
                    {
                        "items": state.ronda_actual,
                        "intervalo_minutos": state.config.get("intervalo_minutos", 45),
                    },
                )
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))

            if self.path == "/api/rate":
                state.calificar(data["id"], int(data["delta"]))
                self._json(200, {"ok": True})
            elif self.path == "/api/postpone":
                state.programar(data.get("minutos"))
                self._json(200, {"ok": True})
            else:
                self.send_error(404)

    return PopupHandler


def abrir_ventana_moderna(puerto: int, navegador: str) -> subprocess.Popen:
    """Abre el pop-up moderno centrado usando Edge/Chrome en modo --app."""
    ancho, alto = 760, 620
    sw, sh = obtener_pantalla()
    x = max(0, (sw - ancho) // 2)
    y = max(0, (sh - alto) // 2)
    perfil = Path(tempfile.mkdtemp(prefix="profe_ingles_popup_"))
    args = [
        navegador,
        f"--app=http://127.0.0.1:{puerto}/",
        "--new-window",
        f"--window-size={ancho},{alto}",
        f"--window-position={x},{y}",
        f"--user-data-dir={perfil}",
        "--no-first-run",
        "--disable-extensions",
    ]
    return subprocess.Popen(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pop-up Entrenador Moderno")
    parser.add_argument("--now", action="store_true", help="Mostrar ronda inmediatamente")
    args = parser.parse_args()

    navegador = encontrar_navegador()
    if not navegador:
        raise RuntimeError("No se encontró Microsoft Edge ni Google Chrome instalado.")

    state = EntrenadorState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), crear_handler(state))
    puerto = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    if args.now or state.config.get("mostrar_al_iniciar", True):
        state.siguiente_disparo = time.time()
    else:
        state.programar()

    while True:
        espera = state.siguiente_disparo - time.time()
        if espera > 0:
            state.evento_espera.clear()
            state.evento_espera.wait(timeout=espera)
            continue

        state.preparar_ronda()
        if not state.ronda_actual:
            state.programar()
            continue

        # Deja programado el ciclo normal por si el usuario cierra con la X
        state.programar()
        proc = abrir_ventana_moderna(puerto, navegador)
        proc.wait()


if __name__ == "__main__":
    main()
