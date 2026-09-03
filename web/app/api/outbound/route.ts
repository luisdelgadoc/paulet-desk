import { NextResponse } from "next/server";
import { verifyConversationOwner } from "@/lib/verifyConversationOwner";

// Proxy delgado hacia el relay (localhost, mismo servidor) -- el relay NUNCA
// expone /outbound al publico (ver desk/Caddyfile, unico path publico sigue
// siendo el webhook de WhatsApp). Este Route Handler corre server-side
// (Node), no en el bundle del navegador -- RELAY_INTERNAL_SECRET nunca
// llega al cliente aunque este archivo viva bajo app/.
const RELAY_URL = "http://localhost:8091/outbound";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const conversationId = body?.conversation_id;
  const message = body?.message;
  if (!conversationId || !message) {
    return NextResponse.json(
      { error: "Faltan conversation_id o message." },
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
      message,
      sender_user_id: verification.userId,
    }),
  });

  const relayData = await relayResp.json().catch(() => ({}));
  if (!relayResp.ok) {
    const message = relayData.detail || relayData.error || "No se pudo enviar el mensaje.";
    return NextResponse.json({ error: message }, { status: relayResp.status });
  }

  return NextResponse.json(relayData, { status: relayResp.status });
}
