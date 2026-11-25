import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BANCO_PATH = BASE_DIR / "data" / "banco.json"
WEB_DATA_PATH = Path(__file__).resolve().parent / "web" / "data.js"


def sync() -> None:
    """Sincroniza data/banco.json hacia web/data.js para uso web y offline."""
    data = json.loads(BANCO_PATH.read_text(encoding="utf-8"))
    contenido = (
        "// Archivo autogenerado desde data/banco.json para compatibilidad offline y web sin CORS\n"
        f"window.BANCO_DATA = {json.dumps(data, ensure_ascii=False, indent=2)};\n"
    )
    WEB_DATA_PATH.write_text(contenido, encoding="utf-8")
    print(f"Sincronizado OK: {len(data.get('vocabulario', []))} vocab, "
          f"{len(data.get('frases', []))} frases, {len(data.get('gramatica', []))} gramatica.")


if __name__ == "__main__":
    sync()
