"""Launcher di UN overlay — processo separato.

Avviato dall'app (main.py -> start_overlays) una volta per overlay attivo.
Per ora e' uno stub: i singoli overlay si aggiungono un pezzo alla volta.

Uso: python -m overlays.run_overlay <nome_overlay>
"""
import sys


def main(name: str):
    if not name:
        print("[overlay] nessun nome overlay indicato")
        return 2
    # TODO: creare la finestra dell'overlay richiesto e avviarne il loop
    print(f"[overlay:{name}] processo avviato (stub)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
