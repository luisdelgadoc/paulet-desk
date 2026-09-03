"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

const STORAGE_BUCKET = "whatsapp-media";
// Suficiente para que cargue el reproductor -- no hace falta mas: si el
// usuario reabre el hilo despues, se pide una signed URL nueva (ver el
// efecto de mas abajo, corre en cada montaje del componente).
const SIGNED_URL_TTL_SECONDS = 300;

const typeLabel: Record<string, string> = {
  audio: "nota de voz",
  image: "imagen",
  video: "video",
  document: "documento",
  sticker: "sticker",
};

// El bucket es privado (ver desk/db/005_whatsapp_media_storage.sql) -- este
// componente pide una signed URL bajo demanda usando la sesion del usuario.
// Supabase solo la entrega si la policy RLS de storage.objects lo permite
// (is_member_of sobre el primer segmento del path, el account_id) -- el
// mismo modelo de seguridad que ya protege las tablas, aplicado a Storage.
export default function MediaBubble({
  path,
  type,
}: {
  path: string;
  type: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;

    supabase.storage
      .from(STORAGE_BUCKET)
      .createSignedUrl(path, SIGNED_URL_TTL_SECONDS)
      .then(({ data, error: signError }) => {
        if (!active) return;
        if (signError || !data) {
          console.error("Error generando signed URL:", signError?.message);
          setError(true);
          return;
        }
        setUrl(data.signedUrl);
      });

    return () => {
      active = false;
    };
  }, [path]);

  const label = typeLabel[type] || type;

  if (error) {
    return (
      <span className="text-xs text-red-500 dark:text-red-400">
        No se pudo cargar {label}.
      </span>
    );
  }

  if (!url) {
    return (
      <span className="text-xs text-wa-text-secondary">Cargando {label}...</span>
    );
  }

  if (type === "audio") {
    return <audio controls src={url} className="max-w-xs" />;
  }
  if (type === "image") {
    // Media privado con signed URL temporal, no un asset estatico que
    // next/image pueda optimizar/cachear con sentido -- se usa <img> plano.
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt="Imagen enviada por el cliente" className="max-w-xs rounded" />;
  }
  if (type === "video") {
    return <video controls src={url} className="max-w-xs rounded" />;
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-sm underline"
    >
      Ver {label}
    </a>
  );
}
