"""Entry point del MURETTO — processo separato.

Avviato dall'app (main.py -> start_muretto) come processo a se'. Da qui parte
il loop del cervello ingegnere. Per ora e' uno stub: la logica arriva dai
moduli portati/riscritti un pezzo alla volta.

Uso: python -m engineer.run_engineer
"""
import sys


def main():
    # TODO: avviare il loop del muretto (lettura core -> decisioni -> voce)
    print("[muretto] processo avviato (stub)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
