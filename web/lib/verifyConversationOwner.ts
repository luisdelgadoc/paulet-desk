// Verificacion compartida para los Route Handlers que actuan en nombre de
// quien tiene una conversacion asignada (/api/outbound, /api/release) --
// evita repetir la misma logica de "resolver usuario + chequear RLS" en
// cada endpoint nuevo (lineamiento de single source of truth).
//
// Resuelve el usuario real a partir de su propio access_token (confirma que
// la sesion es valida y no expiro, sin implementar verificacion de JWT a
// mano), y confirma -- con ESE MISMO token, respetando RLS via is_member_of
// -- que la conversacion existe y esta asignada a ese usuario. No confia en
// nada que declare el cliente.

export const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type VerifyResult =
  | { ok: true; userId: string }
  | { ok: false; status: number; error: string };

export async function verifyConversationOwner(
  authHeader: string | null,
  conversationId: string
): Promise<VerifyResult> {
  if (!authHeader) {
    return { ok: false, status: 401, error: "Falta la sesión." };
  }
  if (!UUID_RE.test(conversationId)) {
    return { ok: false, status: 400, error: "conversation_id inválido." };
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!supabaseUrl || !supabaseAnonKey) {
    console.error("Faltan NEXT_PUBLIC_SUPABASE_URL/ANON_KEY en el servidor");
    return { ok: false, status: 500, error: "Error de configuración del servidor." };
  }

  const userResp = await fetch(`${supabaseUrl}/auth/v1/user`, {
    headers: { apikey: supabaseAnonKey, Authorization: authHeader },
  });
  if (!userResp.ok) {
    return { ok: false, status: 401, error: "Sesión inválida o expirada." };
  }
  const user = await userResp.json();

  const convResp = await fetch(
    `${supabaseUrl}/rest/v1/conversations?id=eq.${conversationId}&select=assigned_to`,
    { headers: { apikey: supabaseAnonKey, Authorization: authHeader } }
  );
  if (!convResp.ok) {
    return { ok: false, status: 502, error: "No se pudo verificar la conversación." };
  }
  const conversations = await convResp.json();
  if (conversations.length === 0) {
    return { ok: false, status: 404, error: "Conversación no encontrada." };
  }
  if (conversations[0].assigned_to !== user.id) {
    return {
      ok: false,
      status: 403,
      error: "Solo quien tiene la conversación asignada puede hacer esto.",
    };
  }

  return { ok: true, userId: user.id };
}
