"""Genera una clave de API para un rol (§7.2) y muestra la entrada de API_KEYS, que solo lleva el hash.

Uso:  python scripts/crear_api_key.py --rol analista --usuario ana
La clave se imprime UNA sola vez: entréguela a su dueño por un canal seguro. En el entorno del despliegue (.env que
no se versiona, o el gestor de secretos) va solo la entrada {"<sha256>": {"usuario", "rol"}} dentro de API_KEYS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets

ROLES = ("operador", "analista", "admin")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rol", required=True, choices=ROLES)
    p.add_argument("--usuario", required=True, help="nombre que quedará en la auditoría (alert_history, modelos)")
    a = p.parse_args()
    clave = secrets.token_urlsafe(32)
    entrada = {hashlib.sha256(clave.encode()).hexdigest(): {"usuario": a.usuario, "rol": a.rol}}
    print(f"Clave para {a.usuario} ({a.rol}); se muestra una sola vez:\n  {clave}\n")
    print("Agregue esta entrada al JSON de API_KEYS del entorno (solo el hash, nunca la clave):")
    print("  " + json.dumps(entrada, ensure_ascii=False))


if __name__ == "__main__":
    main()
