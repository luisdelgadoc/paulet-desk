// Utilidades puras para la lista de conversaciones estilo WhatsApp: preview
// del ultimo mensaje (primeras palabras, o una etiqueta corta si no hay
// texto) y formato de hora (HH:mm si es de hoy, fecha corta si no). Puro
// (sin Supabase, sin DOM) -- mismo criterio de separacion que ya usa el
// relay para sus modulos puros (window_24h.py, media_paths.py), aplicado
// del lado del front por primera vez.

const MEDIA_LABELS: Record<string, string> = {
  audio: "🎤 Nota de voz",
  image: "📷 Foto",
  video: "🎥 Video",
  document: "📄 Documento",
  sticker: "🏷️ Sticker",
};

const PREVIEW_WORD_LIMIT = 5;

export function previewText(body: string | null, type: string): string {
  if (body && body.trim()) {
    const words = body.trim().split(/\s+/);
    const truncated = words.slice(0, PREVIEW_WORD_LIMIT).join(" ");
    return words.length > PREVIEW_WORD_LIMIT ? `${truncated}…` : truncated;
  }
  return MEDIA_LABELS[type] ?? `[${type}]`;
}

// `now` es un parametro (no Date.now() adentro) para poder testear esto
// determinísticamente y para respetar la regla de pureza de React 19 que ya
// aplica el resto del proyecto (ver conversations/[id]/page.tsx, seccion
// "withinWindow") -- el caller decide de donde sale la hora actual.
export function formatListTimestamp(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  if (isToday) {
    return date.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("es-CO", { day: "2-digit", month: "2-digit", year: "2-digit" });
}
