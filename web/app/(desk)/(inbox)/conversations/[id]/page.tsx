"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useParams } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import type { ConversationWithContact, Message } from "@/lib/types";
import Avatar from "@/components/Avatar";
import MediaBubble from "./MediaBubble";

const senderLabel: Record<Message["sender"], string> = {
  customer: "Cliente",
  bot: "el agente",
  human: "Equipo",
};

// Si el canal Realtime nunca confirma la suscripcion (Realtime caido, red
// lenta), no dejar la pantalla cargando para siempre -- se pierde la
// garantia de "sin huecos" descrita abajo, pero es mejor que un spinner
// infinito.
const SUBSCRIBE_FALLBACK_MS = 4000;

// Mismo valor que app/window_24h.py del relay (WINDOW) -- este solo
// controla si se MUESTRA el composer habilitado o el aviso; la verificacion
// real que decide si el envio se acepta vive en el relay, este es puramente
// para no dejar al humano escribir un mensaje que sabemos de antemano que
// Meta va a rechazar.
const WHATSAPP_WINDOW_MS = 24 * 60 * 60 * 1000;

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Busqueda dentro de la conversacion (pedido explicito del usuario,
// 2026-08-08) -- puramente en cliente, sobre los mensajes ya cargados en
// memoria: el hilo ya trae el historial completo de una vez, no pagina, asi
// que no hace falta ninguna consulta nueva a Supabase para esto.
function highlightMatches(text: string, query: string) {
  const q = query.trim();
  if (!q) return text;
  const regex = new RegExp(`(${escapeRegExp(q)})`, "gi");
  return text.split(regex).map((part, i) =>
    part.toLowerCase() === q.toLowerCase() ? (
      <mark key={i} className="rounded bg-yellow-300 text-black">
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

export default function ConversationThreadPage() {
  const params = useParams<{ id: string }>();
  const conversationId = params.id;
  const { userId, loading: loadingSession } = useRequireSession();
  const [conversation, setConversation] = useState<ConversationWithContact | null>(
    null
  );
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingThread, setLoadingThread] = useState(true);
  const [gatePending, setGatePending] = useState(false);
  const [gateError, setGateError] = useState<string | null>(null);
  const [composerText, setComposerText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [threadSearch, setThreadSearch] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Record<string, HTMLLIElement | null>>({});

  // Reinicia la busqueda al cambiar de conversacion -- patron recomendado
  // por React para "ajustar estado cuando cambia una prop" (calculado
  // durante el render, NO dentro de un efecto: las reglas de pureza de
  // React 19 -- react-hooks/set-state-in-effect -- prohiben setState
  // sincronico en el cuerpo de un efecto). Sin esto, una busqueda abierta
  // en una conversacion seguiria "activa" al entrar a otra.
  const [searchResetKey, setSearchResetKey] = useState(conversationId);
  if (conversationId !== searchResetKey) {
    setSearchResetKey(conversationId);
    setSearchOpen(false);
    setThreadSearch("");
  }

  useEffect(() => {
    if (!userId) return;

    let active = true;
    let messagesLoaded = false;

    async function loadConversationMeta() {
      const { data, error } = await supabase
        .from("conversations")
        .select("*, contacts(*)")
        .eq("id", conversationId)
        .single();

      if (!active) return;
      if (error) {
        console.error(
          "Error cargando conversación:",
          error.message
        );
      } else {
        setConversation(data as ConversationWithContact);
      }
    }

    async function loadMessages() {
      if (messagesLoaded) return;
      messagesLoaded = true;

      const { data, error } = await supabase
        .from("messages")
        .select("*")
        .eq("conversation_id", conversationId)
        .order("created_at", { ascending: true });

      if (!active) return;
      if (error) {
        console.error("Error cargando mensajes:", error.message);
      } else {
        setMessages((data ?? []) as Message[]);
      }
      setLoadingThread(false);
    }

    loadConversationMeta();

    // Suscribirse ANTES de traer los mensajes -- hallazgo de la revision
    // conjunta Fase 5+6: si se hiciera al reves (fetch primero, subscribe
    // despues), un mensaje insertado en la ventana entre el fetch y que el
    // canal quede REALMENTE escuchando no lo entrega nadie -- no es un
    // evento que se pueda "perder y reintentar", el INSERT ya paso para
    // cuando el canal esta listo. El guard por id en el handler de INSERT
    // cubre el solape inverso (un mensaje que llega justo mientras
    // loadMessages() ya esta en vuelo).
    //
    // Mismo canal tambien escucha UPDATE de esta conversacion (Fase 7) --
    // si otro miembro del equipo toma o suelta la conversacion mientras la
    // tienes abierta, el estado del boton se actualiza solo.
    const channel = supabase
      .channel(`messages-${conversationId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "messages",
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => {
          const incoming = payload.new as Message;
          setMessages((current) =>
            current.some((m) => m.id === incoming.id)
              ? current
              : [...current, incoming]
          );
        }
      )
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "conversations",
          filter: `id=eq.${conversationId}`,
        },
        (payload) => {
          const updated = payload.new as ConversationWithContact;
          setConversation((current) =>
            current ? { ...current, ...updated, contacts: current.contacts } : current
          );
        }
      )
      .subscribe((status) => {
        if (status === "SUBSCRIBED") {
          loadMessages();
        }
      });

    const fallbackTimer = setTimeout(loadMessages, SUBSCRIBE_FALLBACK_MS);

    return () => {
      active = false;
      clearTimeout(fallbackTimer);
      supabase.removeChannel(channel);
    };
  }, [userId, conversationId]);

  useEffect(() => {
    if (threadSearch.trim()) return; // no auto-scroll al fondo mientras se busca
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, threadSearch]);

  // Date.now() no puede llamarse durante el render ni sincronicamente
  // dentro de un efecto (reglas de pureza de React 19 -- eslint
  // react-hooks/purity y react-hooks/set-state-in-effect). El patron
  // correcto: `now` vive en estado, se actualiza SOLO desde el callback de
  // un setInterval (una suscripcion real a un reloj externo, no un calculo
  // sincronico), y withinWindow se deriva de `now` + `messages` con
  // useMemo -- sin ninguna llamada impura dentro del memo en si.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(interval);
  }, []);

  const withinWindow = useMemo(() => {
    const lastInboundAt = [...messages]
      .reverse()
      .find((m) => m.direction === "inbound")?.created_at;
    return lastInboundAt
      ? now - new Date(lastInboundAt).getTime() < WHATSAPP_WINDOW_MS
      : false;
  }, [messages, now]);

  const matchingMessageIds = useMemo(() => {
    const q = threadSearch.trim().toLowerCase();
    if (!q) return new Set<string>();
    return new Set(
      messages.filter((m) => m.body?.toLowerCase().includes(q)).map((m) => m.id)
    );
  }, [messages, threadSearch]);

  // Salta al primer resultado apenas hay match nuevo -- sin esto, buscar
  // algo que quedo mas arriba del scroll actual obliga a desplazarse a mano
  // para encontrarlo.
  useEffect(() => {
    if (matchingMessageIds.size === 0) return;
    const firstMatchId = messages.find((m) => matchingMessageIds.has(m.id))?.id;
    if (firstMatchId) {
      messageRefs.current[firstMatchId]?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
    // Solo cuando cambia el termino de busqueda, no en cada mensaje nuevo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadSearch]);

  // Gate de human-in-the-loop (Fase 7): el relay deja de reenviar a Hermes
  // apenas assigned_to deja de ser null. RLS + el grant de columna (ver
  // desk/db/003_tighten_rls.sql y 004_messages_rls_policy_not_grant.sql)
  // limitan este UPDATE a exactamente (assigned_to, assigned_at, status) --
  // el navegador no puede tocar nada mas de la fila con este mismo camino.
  //
  // Hallazgo de la revision conjunta Fase 7+8: sin precondicion, un UPDATE
  // sin condicion puede "robar" la conversacion de otro usuario si su UI
  // esta desactualizada (Realtime caido, pestana dormida) -- .is() y .eq()
  // hacen el cambio atomico contra el estado REAL en la base, no el que
  // muestra la pantalla. .select() en la respuesta dice si de verdad aplico.
  async function handleTakeConversation() {
    if (!userId || gatePending) return;
    setGatePending(true);
    setGateError(null);
    const { data, error } = await supabase
      .from("conversations")
      .update({ assigned_to: userId, assigned_at: new Date().toISOString() })
      .eq("id", conversationId)
      .is("assigned_to", null) // precondicion: solo si nadie la tiene
      .select();
    setGatePending(false);
    if (error) {
      console.error("Error tomando la conversación:", error.message);
      setGateError("No se pudo tomar la conversación.");
      return;
    }
    if (!data || data.length === 0) {
      // Alguien mas la tomo justo antes -- Realtime va a traer el estado
      // real en un momento, pero avisamos ya en vez de dejar el boton como
      // si nada hubiera pasado.
      setGateError("Alguien más ya tomó esta conversación.");
      return;
    }
    setConversation((current) =>
      current ? { ...current, ...data[0] } : current
    );
  }

  // Devolver al bot (Fase 9) YA NO es un UPDATE directo: hay que escribir
  // handoff_context_pending (la transcripcion de lo que dijo el humano),
  // columna que el navegador no puede tocar a proposito (mismo motivo que
  // el punto anterior -- ver 003_tighten_rls.sql). Pasa por /api/release,
  // que verifica la sesion y delega al relay (service_role) el calculo de
  // la transcripcion y la escritura real.
  async function handleReleaseConversation() {
    if (!userId || gatePending) return;
    setGatePending(true);
    setGateError(null);

    const { data: sessionData } = await supabase.auth.getSession();
    const accessToken = sessionData.session?.access_token;
    if (!accessToken) {
      setGatePending(false);
      setGateError("Tu sesión expiró -- vuelve a iniciar sesión.");
      return;
    }

    const resp = await fetch("/api/release", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ conversation_id: conversationId }),
    });
    setGatePending(false);

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      setGateError(data.error || "No se pudo devolver la conversación.");
      return;
    }

    setConversation((current) =>
      current ? { ...current, assigned_to: null, assigned_at: null } : current
    );
  }

  // Fase 8: envio saliente del humano. El composer solo aparece si el
  // usuario tiene la conversacion asignada (isMine, ver mas abajo) -- forma
  // parte del mismo modelo del gate: primero se toma la conversacion, luego
  // se responde. El envio real pasa por /api/outbound (Route Handler de
  // Next.js), que reenvia al relay -- nunca se llama a Graph API ni se toca
  // la tabla messages directo desde aca.
  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = composerText.trim();
    if (!text || sending) return;

    setSending(true);
    setSendError(null);

    const { data: sessionData } = await supabase.auth.getSession();
    const accessToken = sessionData.session?.access_token;
    if (!accessToken) {
      setSendError("Tu sesión expiró -- vuelve a iniciar sesión.");
      setSending(false);
      return;
    }

    const resp = await fetch("/api/outbound", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ conversation_id: conversationId, message: text }),
    });

    setSending(false);

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      setSendError(data.error || "No se pudo enviar el mensaje.");
      return;
    }

    setComposerText("");
    // No hace falta agregar el mensaje al estado a mano -- el INSERT que
    // hace el relay dispara el mismo evento Realtime que ya escucha este
    // componente para mensajes entrantes.
  }

  if (loadingSession || !userId) {
    return null;
  }

  const assignedTo = conversation?.assigned_to ?? null;
  const isMine = assignedTo === userId;
  const contactName = conversation?.contacts?.name ?? null;
  const contactPhone = conversation?.contacts?.phone ?? "";

  return (
    <div className="flex flex-1 flex-col bg-wa-chat-bg">
      <header className="flex items-center gap-3 border-b border-wa-border bg-wa-header px-4 py-3">
        <Avatar name={contactName} phone={contactPhone || conversationId} />
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-base font-semibold text-foreground">
            {contactName || contactPhone || "Cargando..."}
          </span>
          {contactName && (
            <span className="truncate text-sm text-wa-text-secondary">
              {contactPhone}
            </span>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={() => {
              setSearchOpen((open) => !open);
              if (searchOpen) setThreadSearch("");
            }}
            title="Buscar en esta conversación"
            aria-label="Buscar en esta conversación"
            className="rounded p-1.5 text-wa-text-secondary hover:bg-wa-hover hover:text-foreground"
          >
            🔍
          </button>

          {assignedTo === null ? (
            <>
              <span className="text-xs text-wa-text-secondary">Con el agente</span>
              <button
                onClick={handleTakeConversation}
                disabled={gatePending}
                className="rounded bg-wa-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                Tomar conversación
              </button>
            </>
          ) : isMine ? (
            <>
              <span className="text-xs text-emerald-700 dark:text-emerald-400">
                La tienes tú
              </span>
              <button
                onClick={handleReleaseConversation}
                disabled={gatePending}
                className="rounded border border-wa-border px-3 py-1.5 text-xs font-medium text-wa-text-secondary disabled:opacity-50"
              >
                Devolver al bot
              </button>
            </>
          ) : (
            <span className="text-xs text-amber-700 dark:text-amber-400">
              Con otro miembro del equipo
            </span>
          )}
        </div>
      </header>

      {searchOpen && (
        <div className="flex items-center gap-2 border-b border-wa-border bg-wa-header px-4 py-2">
          <input
            autoFocus
            type="text"
            value={threadSearch}
            onChange={(e) => setThreadSearch(e.target.value)}
            placeholder="Buscar en esta conversación..."
            className="w-full max-w-sm rounded-lg bg-wa-hover px-3 py-1.5 text-sm text-foreground placeholder:text-wa-text-secondary focus:outline-none"
          />
          {threadSearch.trim() && (
            <span className="shrink-0 text-xs text-wa-text-secondary">
              {matchingMessageIds.size === 0
                ? "Sin resultados"
                : `${matchingMessageIds.size} mensaje${matchingMessageIds.size === 1 ? "" : "s"}`}
            </span>
          )}
        </div>
      )}

      {gateError && (
        <p className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          {gateError}
        </p>
      )}

      <main className="flex-1 overflow-y-auto px-6 py-4">
        {loadingThread ? (
          <p className="text-sm text-wa-text-secondary">
            Cargando mensajes...
          </p>
        ) : messages.length === 0 ? (
          <p className="text-sm text-wa-text-secondary">
            Todavía no hay mensajes.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {messages.map((msg) => {
              const isOutbound = msg.direction === "outbound";
              const isMatch = matchingMessageIds.has(msg.id);
              return (
                <li
                  key={msg.id}
                  ref={(el) => {
                    messageRefs.current[msg.id] = el;
                  }}
                  className={`flex flex-col ${
                    isOutbound ? "items-end" : "items-start"
                  }`}
                >
                  <div
                    className={`max-w-lg rounded-lg px-4 py-2 text-sm text-foreground ${
                      isOutbound
                        ? "bg-wa-bubble-out"
                        : "border border-wa-border bg-wa-bubble-in"
                    } ${isMatch ? "ring-2 ring-yellow-400" : ""}`}
                  >
                    {msg.media_url ? (
                      <MediaBubble path={msg.media_url} type={msg.type} />
                    ) : msg.body ? (
                      highlightMatches(msg.body, threadSearch)
                    ) : (
                      `[${msg.type}]`
                    )}
                  </div>
                  <span className="mt-1 text-xs text-wa-text-secondary">
                    {senderLabel[msg.sender]} ·{" "}
                    {new Date(msg.created_at).toLocaleString("es-CO")}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <div ref={bottomRef} />
      </main>

      {isMine && loadingThread && (
        <div className="border-t border-wa-border bg-wa-header p-4 text-xs text-wa-text-secondary">
          Cargando estado de la conversación...
        </div>
      )}

      {isMine && !loadingThread && (
        <form
          onSubmit={handleSend}
          className="border-t border-wa-border bg-wa-header p-4"
        >
          {!withinWindow && (
            <p className="mb-2 text-xs text-amber-700 dark:text-amber-400">
              Han pasado más de 24h desde el último mensaje del cliente --
              WhatsApp ya no permite mensajes libres, solo plantillas
              aprobadas (no soportado todavía).
            </p>
          )}
          {sendError && (
            <p className="mb-2 text-xs text-red-600 dark:text-red-400">
              {sendError}
            </p>
          )}
          <div className="flex gap-2">
            <textarea
              value={composerText}
              onChange={(e) => setComposerText(e.target.value)}
              disabled={!withinWindow || sending}
              placeholder="Escribe una respuesta..."
              rows={2}
              className="flex-1 resize-none rounded border border-wa-border bg-background px-3 py-2 text-sm text-foreground disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!withinWindow || sending || !composerText.trim()}
              className="rounded bg-wa-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {sending ? "Enviando..." : "Enviar"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
