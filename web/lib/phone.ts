// Puro, sin dependencias -- mismo criterio que lib/messagePreview.ts y
// lib/avatar.ts. El relay guarda `phone` exactamente como Meta manda el
// wa_id: solo digitos, con codigo de pais, sin "+" ni espacios (ver
// desk/relay/app/supabase_client.py, find_or_create_contact -- no hay
// ninguna normalizacion ahi, se persiste tal cual llega). El alta manual de
// contactos desde la web tiene que guardar el telefono en ese MISMO formato
// -- si no calza, cuando ese contacto le escriba de verdad al agente el relay
// no lo va a encontrar por telefono y va a crear un contacto duplicado.
export function normalizePhone(input: string): string {
  return input.replace(/\D/g, "");
}
