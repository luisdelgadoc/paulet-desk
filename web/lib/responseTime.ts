// Puro, sin dependencias -- mismo patron que lib/phone.ts. Calcula el tiempo
// promedio de primera respuesta: por cada conversacion, la diferencia entre
// el primer mensaje del cliente y la primera respuesta (bot o humano) que
// llega DESPUES de ese mensaje. Se promedia sobre todas las conversaciones
// que tienen ambas cosas -- una conversacion donde el cliente escribio y
// todavia nadie respondio no cuenta (ni a favor ni en contra), no se puede
// medir "cuanto tardo" algo que no paso.
//
// Rediseñado tras la una revisión de código posterior (2026-08-10): la version anterior
// recibia conversaciones con TODOS sus mensajes embebidos, sin limite --
// para 100 conversaciones eso podia significar descargar el historial
// completo de cada una solo para sacar 2 timestamps. Ahora recibe una lista
// PLANA de mensajes (conversation_id, direction, created_at), acotada por
// ventana de tiempo + un limite de filas en la consulta que arma esta lista
// (ver app/(desk)/dashboard/page.tsx) -- y agrupa por conversation_id aca
// adentro, no en la consulta.

interface MessageForResponseTime {
  conversation_id: string;
  direction: "inbound" | "outbound";
  created_at: string;
}

// Devuelve el promedio en minutos, o null si no hay ninguna conversacion con
// una primera respuesta medible (evita que el llamador tenga que distinguir
// "0 minutos" de "no hay datos").
export function averageFirstResponseMinutes(
  messages: MessageForResponseTime[]
): number | null {
  const byConversation = new Map<string, MessageForResponseTime[]>();
  for (const m of messages) {
    const list = byConversation.get(m.conversation_id);
    if (list) list.push(m);
    else byConversation.set(m.conversation_id, [m]);
  }

  const diffsMinutes: number[] = [];

  for (const msgs of byConversation.values()) {
    const sorted = [...msgs].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    const firstInbound = sorted.find((m) => m.direction === "inbound");
    if (!firstInbound) continue;

    const firstInboundTime = new Date(firstInbound.created_at).getTime();
    const firstResponse = sorted.find(
      (m) =>
        m.direction === "outbound" &&
        new Date(m.created_at).getTime() > firstInboundTime
    );
    if (!firstResponse) continue;

    const diffMs = new Date(firstResponse.created_at).getTime() - firstInboundTime;
    diffsMinutes.push(diffMs / 60000);
  }

  if (diffsMinutes.length === 0) return null;
  return diffsMinutes.reduce((sum, v) => sum + v, 0) / diffsMinutes.length;
}
