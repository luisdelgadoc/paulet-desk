"""Tests de la construccion del path de Storage (app/media_paths.py).

No necesitan red, servidor, ni .env -- mismo patron que test_window_24h.py.
"""

from app.media_paths import build_storage_path


def test_path_incluye_account_id_como_primer_segmento():
    """La policy RLS de Storage depende de esto -- ver migracion 005."""
    path = build_storage_path("66ea03ae-c616-4b32-9221-b82f5f1a0cef", "wamid.ABC123", "audio/ogg")
    assert path.startswith("66ea03ae-c616-4b32-9221-b82f5f1a0cef/")


def test_path_incluye_el_wamid():
    path = build_storage_path("acc1", "wamid.ABC123", "audio/ogg")
    assert "wamid.ABC123" in path


def test_extension_audio_ogg():
    path = build_storage_path("acc1", "wamid.ABC123", "audio/ogg")
    assert path.endswith(".ogg") or path.endswith(".oga")


def test_extension_imagen_jpeg():
    path = build_storage_path("acc1", "wamid.ABC123", "image/jpeg")
    assert path.endswith(".jpg") or path.endswith(".jpeg")


def test_mime_con_parametros_extra_no_rompe_la_extension():
    """WhatsApp Cloud API manda mime_type con parametros extra, ej.
    'audio/ogg; codecs=opus' -- mimetypes.guess_extension no reconoce eso
    tal cual, hay que cortar en el ';' antes de consultarlo."""
    path = build_storage_path("acc1", "wamid.ABC123", "audio/ogg; codecs=opus")
    assert path.endswith(".ogg") or path.endswith(".oga")


def test_mime_desconocido_no_revienta():
    """Un mime_type que mimetypes no reconoce no debe lanzar excepcion --
    el path queda sin extension, mejor eso que perder el mensaje."""
    path = build_storage_path("acc1", "wamid.ABC123", "application/x-whatsapp-mystery")
    assert path == "acc1/wamid.ABC123"
