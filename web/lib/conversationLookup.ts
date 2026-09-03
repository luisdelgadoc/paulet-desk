// Puro, extraido de app/(desk)/pipeline/page.tsx (una revisión de código posterior,
// 2026-08-10: la misma pregunta -- "a que conversacion pertenece este
// contacto" -- se resolvia dos veces con dos tecnicas distintas). Se
// mantienen las 2 tecnicas a proposito, no se unifican:
//
//  - app/(desk)/contacts/page.tsx resuelve esto con un embed REVERSO de
//    PostgREST (contacts -> conversations) con order+limit aplicados al
//    embed -- una sola consulta hace las dos cosas, mismo patron ya
//    verificado contra Supabase real (ver lib/types.ts,
//    ContactWithConversation).
//  - app/(desk)/pipeline/page.tsx no puede usar ese mismo truco sin un
//    embed anidado de 2 niveles (deals -> contacts -> conversations) que
//    nunca se verifico contra Supabase real -- en vez de arriesgarse, hace
//    una consulta aparte a conversations y arma el mapa aca.
//
// Lo que SI se comparte, para no duplicar la logica de agrupamiento en si.
export interface ConversationForLookup {
  id: string;
  contact_id: string;
  created_at: string;
}

// Dado un listado de conversaciones (en cualquier orden), arma un mapa
// contact_id -> id de su conversacion mas reciente.
export function latestConversationByContact(
  conversations: ConversationForLookup[]
): Map<string, string> {
  const sorted = [...conversations].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  const map = new Map<string, string>();
  for (const c of sorted) {
    if (!map.has(c.contact_id)) map.set(c.contact_id, c.id);
  }
  return map;
}
