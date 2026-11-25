import argparse
import json
import random
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

BASE_DIR = Path(__file__).resolve().parent.parent
BANCO_PATH = BASE_DIR / "data" / "banco.json"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
PROGRESO_PATH = Path(__file__).resolve().parent / "progreso.json"

COLORS = {
    "bg": "#0f172a",
    "card": "#1e293b",
    "border": "#334155",
    "text": "#f8fafc",
    "muted": "#94a3b8",
    "accent": "#38bdf8",
    "success": "#22c55e",
    "warn": "#f59e0b",
    "btn_bg": "#334155",
}


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


def hablar_ingles(texto: str, velocidad: int = 0) -> None:
    """Reproduce texto en inglés usando el sintetizador nativo de Windows."""
    texto_limpio = texto.replace("'", "''").replace('"', " ")
    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {int(velocidad)}; "
        "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | Select-Object -First 1; "
        "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
        f"$s.Speak('{texto_limpio}')"
    )

    def _run() -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    threading.Thread(target=_run, daemon=True).start()


class PopupEntrenador:
    """Ventana flotante periódica para repasar vocabulario y frases de Friends."""

    def __init__(self, abrir_ahora: bool = False) -> None:
        self.config = cargar_json(
            CONFIG_PATH,
            {
                "intervalo_minutos": 45,
                "preguntas_por_sesion": 2,
                "mostrar_al_iniciar": True,
                "siempre_encima": True,
                "velocidad_voz": 0,
            },
        )
        self.progreso = cargar_json(PROGRESO_PATH, {})
        self.pausado = False
        self.ventana: tk.Toplevel | None = None
        self.item_actual: dict | None = None
        self.pendientes_ronda = 0

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Profe Inglés - Fondo")

        if abrir_ahora or self.config.get("mostrar_al_iniciar", True):
            self.root.after(200, self.iniciar_ronda)
        else:
            self.programar_siguiente()

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
                }
            )
        for f in banco.get("frases", []):
            bloques = f.get("bloques", [])
            fonetica = "\n".join(f"• {b['en']}\n  [{b['fonetica']}]" for b in bloques)
            items.append(
                {
                    "id": f["id"],
                    "tipo": f"Shadowing ({f.get('personaje', 'Friends')})",
                    "dia": f.get("dia", "?"),
                    "episodio": f.get("episodio", ""),
                    "pregunta": f["es"],
                    "respuesta": f["en"],
                    "extra": fonetica,
                }
            )
        return items

    def elegir_item(self) -> dict | None:
        """Selecciona un ítem dando más peso a los que tienen menor nivel de dominio."""
        items = self.obtener_items()
        if not items:
            return None
        pesos = []
        for it in items:
            nivel = self.progreso.get(it["id"], 0)
            peso = max(1, 6 - nivel)
            pesos.append(peso)
        return random.choices(items, weights=pesos, k=1)[0]

    def programar_siguiente(self, minutos: int | None = None) -> None:
        """Programa la siguiente aparición del pop-up."""
        mins = minutos if minutos is not None else int(self.config.get("intervalo_minutos", 45))
        ms = max(1, mins) * 60 * 1000
        self.root.after(ms, self.iniciar_ronda)

    def iniciar_ronda(self) -> None:
        """Abre una nueva ronda de preguntas si no está pausado."""
        if self.pausado:
            self.pausado = False
        self.pendientes_ronda = int(self.config.get("preguntas_por_sesion", 2))
        self.mostrar_tarjeta()

    def mostrar_tarjeta(self) -> None:
        """Crea o actualiza la ventana flotante con la pregunta actual."""
        item = self.elegir_item()
        if not item:
            self.programar_siguiente()
            return
        self.item_actual = item

        if self.ventana and self.ventana.winfo_exists():
            self.ventana.destroy()

        win = tk.Toplevel(self.root)
        self.ventana = win
        win.title("Profe Inglés — Repaso Rápido")
        win.configure(bg=COLORS["bg"])
        win.resizable(False, False)
        if self.config.get("siempre_encima", True):
            win.attributes("-topmost", True)

        ancho, alto = 460, 390
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = sw - ancho - 24
        y = sh - alto - 64
        win.geometry(f"{ancho}x{alto}+{x}+{y}")
        win.protocol("WM_DELETE_WINDOW", self.posponer)

        # Cabecera
        header = tk.Frame(win, bg=COLORS["bg"])
        header.pack(fill="x", padx=18, pady=(14, 6))

        tag = f"{item['tipo']} · Día {item['dia']} ({item['episodio']})"
        tk.Label(
            header,
            text=tag,
            fg=COLORS["accent"],
            bg=COLORS["bg"],
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        tk.Label(
            header,
            text=f"Cada {self.config.get('intervalo_minutos', 45)} min",
            fg=COLORS["muted"],
            bg=COLORS["bg"],
            font=("Segoe UI", 8),
        ).pack(side="right")

        # Tarjeta principal
        card = tk.Frame(win, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        card.pack(fill="both", expand=True, padx=18, pady=6)

        tk.Label(
            card,
            text="¿Cómo lo dices en inglés?",
            fg=COLORS["muted"],
            bg=COLORS["card"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=14, pady=(12, 4))

        tk.Label(
            card,
            text=item["pregunta"],
            fg=COLORS["text"],
            bg=COLORS["card"],
            font=("Segoe UI", 12, "bold"),
            wraplength=390,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 10))

        self.lbl_resp = tk.Label(
            card,
            text="",
            fg=COLORS["success"],
            bg=COLORS["card"],
            font=("Segoe UI", 11, "bold"),
            wraplength=390,
            justify="left",
        )
        self.lbl_resp.pack(anchor="w", padx=14, pady=(2, 4))

        self.lbl_extra = tk.Label(
            card,
            text="",
            fg=COLORS["muted"],
            bg=COLORS["card"],
            font=("Segoe UI", 9),
            wraplength=390,
            justify="left",
        )
        self.lbl_extra.pack(anchor="w", padx=14, pady=(0, 10))

        # Botonera
        actions = tk.Frame(win, bg=COLORS["bg"])
        actions.pack(fill="x", padx=18, pady=(6, 14))

        self.btn_ver = tk.Button(
            actions,
            text="👀 Ver respuesta",
            command=self.revelar,
            bg=COLORS["accent"],
            fg="#0f172a",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        )
        self.btn_ver.pack(side="left")

        self.btn_audio = tk.Button(
            actions,
            text="🔊 Escuchar",
            command=self.reproducir_audio,
            bg=COLORS["btn_bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )
        self.btn_audio.pack(side="left", padx=(6, 0))

        self.btn_ok = tk.Button(
            actions,
            text="✅ Lo dominé",
            command=lambda: self.calificar(1),
            bg=COLORS["success"],
            fg="#0f172a",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )

        self.btn_repasar = tk.Button(
            actions,
            text="🔁 Repasar",
            command=lambda: self.calificar(-1),
            bg=COLORS["warn"],
            fg="#0f172a",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )

        tk.Button(
            actions,
            text="⏸ Posponer",
            command=self.posponer,
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 8),
            relief="flat",
            cursor="hand2",
        ).pack(side="right")

    def revelar(self) -> None:
        """Muestra la respuesta en inglés, el detalle fonético/ejemplo y los botones de calificación."""
        if not self.item_actual:
            return
        self.lbl_resp.config(text=self.item_actual["respuesta"])
        self.lbl_extra.config(text=self.item_actual["extra"])
        self.btn_ver.pack_forget()
        self.btn_ok.pack(side="left", padx=(0, 6))
        self.btn_repasar.pack(side="left")
        self.reproducir_audio()

    def reproducir_audio(self) -> None:
        """Reproduce en voz alta el texto en inglés de la tarjeta actual."""
        if self.item_actual:
            hablar_ingles(self.item_actual["respuesta"], self.config.get("velocidad_voz", 0))

    def calificar(self, delta: int) -> None:
        """Actualiza el nivel de dominio y pasa a la siguiente tarjeta o cierra la ronda."""
        if self.item_actual:
            iid = self.item_actual["id"]
            actual = self.progreso.get(iid, 0)
            self.progreso[iid] = max(0, min(5, actual + delta))
            guardar_json(PROGRESO_PATH, self.progreso)

        self.pendientes_ronda -= 1
        if self.pendientes_ronda > 0:
            self.mostrar_tarjeta()
        else:
            self.posponer()

    def posponer(self) -> None:
        """Cierra la ventana actual y programa el próximo aviso."""
        if self.ventana and self.ventana.winfo_exists():
            self.ventana.destroy()
        self.programar_siguiente()

    def run(self) -> None:
        """Inicia el bucle principal de Tkinter."""
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Pop-up Entrenador de Inglés")
    parser.add_argument("--now", action="store_true", help="Mostrar tarjeta inmediatamente al arrancar")
    args = parser.parse_args()
    app = PopupEntrenador(abrir_ahora=args.now)
    app.run()


if __name__ == "__main__":
    main()
