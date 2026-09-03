import { NextResponse } from "next/server";
import { verifyConversationOwner } from "@/lib/verifyConversationOwner";

// Proxy delgado hacia el relay (localhost, mismo servidor) -- mismo patron que
// /api/outbound. Existe porque devolver la conversacion al bot (Fase 9) ya
// no es un simple UPDATE desde el navegador: hay que escribir
// handoff_context_pending, columna que el navegador NO puede tocar a
// proposito (ver desk/db/003_tighten_rls.sql -- el grant de columna solo
// cubre assigned_to/assigned_at/status). Calcular la transcripcion y
// escribirla requiere la service_role key, que solo tiene el relay.
const RELAY_URL = "http://localhost:8091/release-conversation";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const conversationId = body?.conversation_id;
  if (!conversationId) {
    return NextResponse.json(
      { error: "Falta conversation_id." },
      { status: 400 }
    );
  }

  const verification = await verifyConversationOwner(
    request.headers.get("authorization"),
    conversationId
  );
  if (!verification.ok) {
    return NextResponse.json(
      { error: verification.error },
      { status: verification.status }
    );
  }

  const relaySecret = process.env.RELAY_INTERNAL_SECRET;
  if (!relaySecret) {
    console.error("Falta RELAY_INTERNAL_SECRET en el servidor");
    return NextResponse.json(
      { error: "Error de configuración del servidor." },
      { status: 500 }
    );
  }

  const relayResp = await fetch(RELAY_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Relay-Secret": relaySecret,
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      sender_user_id: verification.userId,
    }),
  });

  const relayData = await relayResp.json().catch(() => ({}));
  if (!relayResp.ok) {
    const message =
      relayData.detail || relayData.error || "No se pudo devolver la conversación.";
    return NextResponse.json({ error: message }, { status: relayResp.status });
  }

  return NextResponse.json(relayData, { status: relayResp.status });
}
