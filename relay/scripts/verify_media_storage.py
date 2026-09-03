"""Verifica el bucket de Storage y su policy RLS (Fase 10, migracion 005) --
SIN pasar por Graph API. Sube un archivo local real (uno de los .ogg que
Hermes ya descargo en pruebas anteriores, en
/root/.hermes/profiles/demo/platforms/whatsapp_cloud/media/) directo a
Storage con la service_role key, simulando el ultimo paso de
app/whatsapp_media.py. Confirma que el objeto quedo en el bucket y que se
puede generar una signed URL.

No prueba la descarga de Graph API en si (esa parte necesita un media_id
vigente de Meta, que expira) -- para esa parte y para confirmar que un
usuario real de la bandeja puede REPRODUCIR el archivo (RLS desde el
navegador, no desde service_role), hace falta una nota de voz real enviada
durante esta sesion.

Uso: python3 scripts/verify_media_storage.py
"""

import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

RELAY_ENV = "/root/paulet-desk/relay/.env"
ACCOUNT_ID = "66ea03ae-c616-4b32-9221-b82f5f1a0cef"
BUCKET = "whatsapp-media"
LOCAL_OGG_DIR = Path("/root/.hermes/profiles/demo/platforms/whatsapp_cloud/media")

relay_env = dotenv_values(RELAY_ENV)
supabase_url = relay_env["SUPABASE_URL"]
supabase_key = relay_env["SUPABASE_SERVICE_ROLE_KEY"]
sb_headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}


def find_local_ogg() -> Path:
    candidates = sorted(LOCAL_OGG_DIR.glob("*.ogg"))
    if not candidates:
        print(f"‼️  No hay .ogg en {LOCAL_OGG_DIR} -- no se puede probar sin un archivo real")
        sys.exit(1)
    return candidates[0]


def upload_to_storage(local_path: Path, storage_path: str) -> None:
    resp = httpx.post(
        f"{supabase_url}/storage/v1/object/{BUCKET}/{storage_path}",
        headers={**sb_headers, "Content-Type": "audio/ogg", "x-upsert": "true"},
        content=local_path.read_bytes(),
        timeout=30.0,
    )
    print(f"Upload -> HTTP {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()


def create_signed_url(storage_path: str) -> str | None:
    resp = httpx.post(
        f"{supabase_url}/storage/v1/object/sign/{BUCKET}/{storage_path}",
        headers={**sb_headers, "Content-Type": "application/json"},
        json={"expiresIn": 60},
        timeout=15.0,
    )
    print(f"Sign -> HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        return None
    return resp.json().get("signedURL")


def confirm_downloadable(signed_url_path: str) -> bool:
    resp = httpx.get(f"{supabase_url}/storage/v1{signed_url_path}", timeout=15.0)
    return resp.status_code == 200 and len(resp.content) > 0


local_ogg = find_local_ogg()
storage_path = f"{ACCOUNT_ID}/verify-media-storage-test.ogg"
# Guard de seguridad (hallazgo de la una revisión de código posterior, 2026-08-08):
# este script sube al bucket de Storage de PRODUCCION real -- el nombre fijo
# "verify-media-storage-test.ogg" es lo que evita pisar un wamid real (que
# nunca contendria ese texto). Si alguien lo cambia a mano sin fijarse, esto
# revienta fuerte y temprano en vez de arriesgar sobreescribir un archivo real.
assert "verify-media-storage-test" in storage_path, (
    "storage_path no tiene el marcador de archivo de prueba esperado -- este script "
    "escribe contra el bucket de Storage de produccion real."
)
print(f"--- Subiendo {local_ogg.name} ({local_ogg.stat().st_size} bytes) a {BUCKET}/{storage_path} ---")
upload_to_storage(local_ogg, storage_path)

print("\n--- Generando signed URL (simula lo que hace el navegador) ---")
signed_path = create_signed_url(storage_path)

print("\n--- Resultado ---")
if signed_path and confirm_downloadable(signed_path):
    print("✅ STORAGE OK: subida, signed URL generada, y el archivo se descarga con esa URL.")
    print("   Pendiente: confirmar que RLS deja pasar a un usuario real (no service_role) --")
    print("   eso se prueba solo con una nota de voz real desde el navegador.")
    sys.exit(0)
else:
    print("‼️  Algo fallo -- revisar que la migracion 005 se haya corrido en Supabase (bucket + policy).")
    sys.exit(1)
