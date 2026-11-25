# Profe Inglés (Método *Friends*)

Sistema personal de entrenamiento vocal (Shadowing), vocabulario y gramática con *Friends*.

## Estructura del Proyecto
- `AGENTS.md` / `STATUS.md` / `MEMORY.md` — Reglas, progreso diario y memoria del estudiante.
- `data/banco.json` — Base de datos única del curso (frases, vocabulario y gramática).
- `app/` — Aplicación de repaso:
  - `app/pc/` — Pop-up Entrenador para Windows (`Iniciar_Popup.bat`).
  - `app/web/` — App Web Móvil PWA (`Abrir_Web_Local.bat` o GitHub Pages).
  - `app/sync_data.py` — Sincroniza `data/banco.json` → `app/web/data.js`.
