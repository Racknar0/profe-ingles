import argparse
import ctypes
from ctypes import wintypes
import json
import os
import random
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BANCO_PATH = BASE_DIR / "data" / "banco.json"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
PROGRESO_PATH = Path(__file__).resolve().parent / "progreso.json"
PORT_PATH = Path(__file__).resolve().parent / ".port"
UI_PATH = Path(__file__).resolve().parent / "popup_ui.html"
ICON_ICO_PATH = Path(__file__).resolve().parent / "icon.ico"
ICON_PNG_PATH = BASE_DIR / "app" / "web" / "icon-192.png"

try:
    from app.pc.tray import TrayIcon
except ImportError:
    from tray import TrayIcon


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
    """Busca Google Chrome o Microsoft Edge en Windows para modo --app."""
    candidatos = [
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LocalAppData", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LocalAppData", "")) / "Microsoft/Edge/Application/msedge.exe",
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
        self.proc_actual: subprocess.Popen | None = None
        self.salir = False

    def obtener_items(self) -> tuple[list[dict], list[dict], list[dict]]:
        """Construye listas separadas de vocabulario, frases y píldoras gramaticales."""
        banco = cargar_json(BANCO_PATH, {"vocabulario": [], "frases": [], "gramatica": []})
        vocab: list[dict] = []
        frases: list[dict] = []
        gramatica: list[dict] = []

        for v in banco.get("vocabulario", []):
            vocab.append(
                {
                    "id": v["id"],
                    "tipo": "Vocabulario",
                    "dia": v.get("dia", "?"),
                    "episodio": v.get("episodio", ""),
                    "pregunta": v["es"],
                    "respuesta": v["en"],
                    "extra": f"Ejemplo: {v.get('ejemplo', '')}" if v.get("ejemplo") else "",
                    "extra_es": v.get("ejemplo_es", ""),
                    "bloques": [],
                    "es_gramatica": False,
                    "nivel": self.progreso.get(v["id"], 0),
                }
            )
        for f in banco.get("frases", []):
            frases.append(
                {
                    "id": f["id"],
                    "tipo": f"Shadowing ({f.get('personaje', 'Friends')})",
                    "dia": f.get("dia", "?"),
                    "episodio": f.get("episodio", ""),
                    "pregunta": f["es"],
                    "respuesta": f["en"],
                    "extra": "",
                    "bloques": f.get("bloques", []),
                    "es_gramatica": False,
                    "nivel": self.progreso.get(f["id"], 0),
                }
            )
        for g in banco.get("gramatica", []):
            gramatica.append(
                {
                    "id": g["id"],
                    "tipo": "Píldora Gramatical",
                    "dia": g.get("dia", "?"),
                    "episodio": g.get("episodio", ""),
                    "titulo": g.get("titulo", ""),
                    "uso": g.get("uso", ""),
                    "formula": g.get("formula", ""),
                    "ejemplos": g.get("ejemplos", []),
                    "es_gramatica": True,
                    "nivel": self.progreso.get(g["id"], 0),
                }
            )
        return vocab, frases, gramatica

    def _elegir_ponderado(self, pool: list[dict]) -> dict | None:
        if not pool:
            return None
        pesos = [max(1, 6 - it["nivel"]) for it in pool]
        return random.choices(pool, weights=pesos, k=1)[0]

    def preparar_ronda(self) -> list[dict]:
        """Arma una ronda completa de 3 pilares: 1 Vocabulario + 1 Shadowing + 1 Gramática."""
        vocab, frases, gramatica = self.obtener_items()
        seleccionados: list[dict] = []

        for pool in (vocab, frases, gramatica):
            elegido = self._elegir_ponderado(pool)
            if elegido:
                seleccionados.append(elegido)

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

    def cambiar_intervalo(self, minutos: int) -> None:
        """Guarda el nuevo intervalo en config.json y actualiza el temporizador."""
        with self.lock:
            self.config["intervalo_minutos"] = int(minutos)
            guardar_json(CONFIG_PATH, self.config)
            self.siguiente_disparo = time.time() + max(1, int(minutos)) * 60
        self.evento_espera.set()

    def practicar_ahora(self) -> None:
        """Dispara una ronda de práctica de forma inmediata."""
        with self.lock:
            self.siguiente_disparo = time.time()
        self.evento_espera.set()

    def detener(self) -> None:
        """Finaliza el proceso en segundo plano limpiamente."""
        self.salir = True
        if self.proc_actual and self.proc_actual.poll() is None:
            self.proc_actual.terminate()
        PORT_PATH.unlink(missing_ok=True)
        self.evento_espera.set()
        os._exit(0)


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
            elif self.path == "/icon.png":
                icon_bytes = ICON_PNG_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(icon_bytes)))
                self.end_headers()
                self.wfile.write(icon_bytes)
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
            elif self.path == "/api/intervalo":
                state.cambiar_intervalo(int(data.get("minutos", 45)))
                self._json(200, {"ok": True})
            elif self.path == "/api/practicar":
                state.practicar_ahora()
                self._json(200, {"ok": True})
            else:
                self.send_error(404)

    return PopupHandler


def mantener_siempre_encima(proc: subprocess.Popen) -> None:
    """Fuerza HWND_TOPMOST en la ventana del pop-up mientras esté abierta."""
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    HWND_TOPMOST = wintypes.HWND(-1)
    titulo_objetivo = "Profe Inglés — Entrenador"

    def _forzar() -> None:
        while proc.poll() is None:
            def _enum_cb(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if titulo_objetivo in buf.value:
                        # SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE = 0x0013
                        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0013)
                return True

            user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
            time.sleep(0.5)

    threading.Thread(target=_forzar, daemon=True).start()


def abrir_ventana_moderna(puerto: int, navegador: str) -> subprocess.Popen:
    """Abre el pop-up moderno centrado usando Chrome/Edge en modo --app."""
    ancho, alto = 900, 620
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
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-extensions",
    ]
    if "msedge" in navegador.lower():
        args.append("--guest")
    return subprocess.Popen(args)


def asegurar_instancia_unica(abrir_si_existe: bool = False) -> object:
    """Evita dobles ejecuciones usando un Mutex nativo de Windows."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    mutex = kernel32.CreateMutexW(None, False, "Local\\ProfeInglesPopupMutex")
    ERROR_ALREADY_EXISTS = 183
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        if abrir_si_existe and PORT_PATH.exists():
            try:
                puerto = PORT_PATH.read_text(encoding="utf-8").strip()
                req = urllib.request.Request(
                    f"http://127.0.0.1:{puerto}/api/practicar",
                    data=b"{}",
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=2)
            except Exception:
                pass
        raise SystemExit(0)
    return mutex


def main() -> None:
    parser = argparse.ArgumentParser(description="Pop-up Entrenador Moderno")
    parser.add_argument("--now", action="store_true", help="Mostrar ronda inmediatamente")
    args = parser.parse_args()
    _mutex = asegurar_instancia_unica(abrir_si_existe=args.now)

    navegador = encontrar_navegador()
    if not navegador:
        raise RuntimeError("No se encontró Microsoft Edge ni Google Chrome instalado.")

    state = EntrenadorState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), crear_handler(state))
    puerto = server.server_address[1]
    PORT_PATH.write_text(str(puerto), encoding="utf-8")
    threading.Thread(target=server.serve_forever, daemon=True).start()

    tray = TrayIcon(
        icon_path=ICON_ICO_PATH,
        on_practicar=state.practicar_ahora,
        on_intervalo=state.cambiar_intervalo,
        get_intervalo=lambda: int(state.config.get("intervalo_minutos", 45)),
        on_salir=state.detener,
    )
    tray.iniciar()

    if args.now or state.config.get("mostrar_al_iniciar", True):
        state.siguiente_disparo = time.time()
    else:
        state.programar()

    while not state.salir:
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
        state.proc_actual = proc
        mantener_siempre_encima(proc)
        proc.wait()
        state.proc_actual = None

    tray.remover()


if __name__ == "__main__":
    main()
