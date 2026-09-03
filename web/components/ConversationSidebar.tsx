"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import { previewText, formatListTimestamp } from "@/lib/messagePreview";
import Avatar from "./Avatar";
import type { ConversationWithContact } from "@/lib/types";

// Techo de la lista -- ver el mismo comentario que tenia esto en el antiguo
// app/page.tsx: 100 alcanza de sobra para el volumen real de esta demo.
const CONVERSATION_LIST_LIMIT = 100;

// Extraido de lo que antes era app/page.tsx completo (Fase 6) para vivir en
// un layout compartido -- ahora la lista queda SIEMPRE visible junto al
// hilo, en vez de ser una pagina aparte a la que se navegaba (pedido
// explicito del usuario, 2026-08-08: "es muy dificil que sea una sola
// interfaz?"). Beneficio de que viva en el layout, no en cada page: Next.js
// NO remonta el layout al navegar ENTRE conversaciones -- el fetch y el
// canal Realtime de la lista se abren una vez, no en cada click.
//
// Fase Contactos (2026-08-10): este componente se movio a
// app/(desk)/(inbox)/layout.tsx (antes vivia en app/(desk)/layout.tsx a
// secas) -- especifico de "/" y "/conversations/[id]", para que /contacts
// no lo monte. Efecto colateral real, no solo cosmetico: ir a /contacts y
// volver a "/" SI desmonta y remonta este componente (route group distinto),
// a diferencia de navegar entre conversaciones dentro del mismo grupo -- un
// refetch de las 100 conversaciones + reapertura del canal Realtime en cada
// ida y vuelta. Costo aceptado a proposito (Contactos es una seccion
// separada, no un detalle de una conversacion), pero real.
export default function ConversationSidebar() {
  const pathname = usePathname();
  const [conversations, setConversations] = useState<ConversationWithContact[]>(
    []
  );
  const [loadingList, setLoadingList] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let active = true;

    async function loadConversations() {
      // El embed de "messages" con order+limit aplicado AL EMBED (no a la
      // tabla principal) trae el ultimo mensaje de cada conversacion en la
      // misma consulta -- verificado contra Supabase real antes de escribir
      // esto (ver comentario en lib/types.ts). Sin este embed habria que
      // hacer una consulta aparte por conversacion (N+1) o denormalizar una
      // columna en la tabla y tocar el relay -- ninguna de las dos hacia
      // falta.
      const { data, error } = await supabase
        .from("conversations")
        .select("*, contacts(*), messages(body, type, created_at)")
        .order("last_message_at", { ascending: false, nullsFirst: false })
        .order("created_at", { ascending: false, foreignTable: "messages" })
        .limit(1, { foreignTable: "messages" })
        .limit(CONVERSATION_LIST_LIMIT);

      if (!active) return;
      if (error) {
        console.error("Error cargando conversaciones:", error.message);
      } else {
        setConversations((data ?? []) as ConversationWithContact[]);
      }
      setLoadingList(false);
    }

    loadConversations();

    // Un solo canal para toda la vida del layout (a diferencia de antes, que
    // se abria y cerraba en cada navegacion). Escucha cualquier cambio en
    // conversations -- alcanza para refrescar el preview del ultimo mensaje
    // tambien: los 3 caminos que insertan un mensaje (inbound, respuesta de
    // el agente, respuesta humana) SIEMPRE tocan conversations.last_message_at
    // via touch_conversation_last_message (ver app/main.py del relay), asi
    // que un mensaje nuevo dispara este mismo evento -- no hace falta un
    // segundo canal escuchando "messages" aparte.
    const channel = supabase
      .channel("conversations-list")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "conversations" },
        () => loadConversations()
      )
      .subscribe();

    return () => {
      active = false;
      supabase.removeChannel(channel);
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((conv) => {
      const name = conv.contacts?.name?.toLowerCase() ?? "";
      const phone = conv.contacts?.phone?.toLowerCase() ?? "";
      return name.includes(q) || phone.includes(q);
    });
  }, [conversations, search]);

  return (
    <aside className="flex w-[380px] shrink-0 flex-col border-r border-wa-border bg-wa-list-bg">
      <header className="flex items-center justify-between border-b border-wa-border bg-wa-header px-4 py-3">
        <h1 className="text-base font-semibold text-foreground">Paulet Desk</h1>
      </header>

      <div className="border-b border-wa-border px-3 py-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar contacto o número"
          className="w-full rounded-lg bg-wa-hover px-3 py-1.5 text-sm text-foreground placeholder:text-wa-text-secondary focus:outline-none"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {loadingList ? (
          <p className="p-6 text-sm text-wa-text-secondary">
            Cargando conversaciones...
          </p>
        ) : filtered.length === 0 ? (
          <p className="p-6 text-sm text-wa-text-secondary">
            {conversations.length === 0
              ? "No hay conversaciones todavía."
              : "Sin resultados para esa búsqueda."}
          </p>
        ) : (
          <ul className="divide-y divide-wa-border">
            {filtered.map((conv) => {
              const isActive = pathname === `/conversations/${conv.id}`;
              const lastMessage = conv.messages?.[0];
              return (
                <li key={conv.id}>
                  <Link
                    href={`/conversations/${conv.id}`}
                    className={`flex items-center gap-3 px-3 py-3 hover:bg-wa-hover ${
                      isActive ? "bg-wa-hover" : ""
                    }`}
                  >
                    <Avatar
                      name={conv.contacts?.name ?? null}
                      phone={conv.contacts?.phone ?? conv.id}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium text-foreground">
                          {conv.contacts?.name ||
                            conv.contacts?.phone ||
                            "Contacto desconocido"}
                        </span>
                        {conv.last_message_at && (
                          <span className="shrink-0 text-xs text-wa-text-secondary">
                            {formatListTimestamp(conv.last_message_at)}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm text-wa-text-secondary">
                          {lastMessage
                            ? previewText(lastMessage.body, lastMessage.type)
                            : "..."}
                        </span>
                        {conv.assigned_to && (
                          <span className="shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                            Humano
                          </span>
                        )}
                      </div>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
