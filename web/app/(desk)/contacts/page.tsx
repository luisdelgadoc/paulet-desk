"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { normalizePhone } from "@/lib/phone";
import type { ContactWithConversation } from "@/lib/types";

// Techo de la lista SIN búsqueda -- mismo criterio que CONVERSATION_LIST_LIMIT
// en components/ConversationSidebar.tsx (evitar traer la tabla completa sin
// cota), pero NO el mismo valor -- ahi es 100, aca 200 a proposito: se
// esperan mas contactos que conversaciones abiertas simultaneas. Con
// búsqueda activa NO aplica este límite -- ver SEARCH_RESULT_LIMIT: la
// búsqueda corre server-side sobre TODA la tabla, no sobre estos 200.
const CONTACT_LIST_LIMIT = 200;
const SEARCH_RESULT_LIMIT = 50;
const SEARCH_DEBOUNCE_MS = 300;

type FormState = { name: string; phone: string; email: string; company: string };
const EMPTY_FORM: FormState = { name: "", phone: "", email: "", company: "" };

// Selección compartida por la carga inicial y la búsqueda -- mismo shape,
// una sola definición.
const CONTACT_SELECT = "*, conversations(id)";

export default function ContactsPage() {
  const router = useRouter();
  const { accountId, loading: loadingSession } = useRequireSession();

  // Lista base (sin búsqueda) -- los primeros CONTACT_LIST_LIMIT por fecha.
  const [contacts, setContacts] = useState<ContactWithConversation[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Búsqueda -- server-side, no client-side sobre `contacts`. Hallazgo real
  // de la una revisión de código posterior: filtrar en cliente sobre solo los 200 más
  // recientes hacía que buscar a alguien real pero viejo devolviera "Sin
  // resultados", indistinguible de "no existe". null = no hay búsqueda
  // activa, se muestra `contacts`.
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<ContactWithConversation[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // Ref, no solo el estado `saving` -- un Enter mantenido o un doble click
  // muy rápido puede disparar dos submits antes de que el primer
  // setSaving(true) se refleje en el render del segundo. El ref es
  // sincrónico, no espera a que React vuelva a renderizar.
  const savingRef = useRef(false);

  // Carga inicial y refresh manual (botón ↻ y tras crear un contacto) --
  // SIN Realtime a propósito: `contacts` nunca se agregó a la publicación
  // `supabase_realtime` (solo `messages`/`conversations` en
  // 001_initial_schema.sql), y no hace falta sumar esa pieza -- mismo
  // criterio ya usado para el Dashboard (ver ARCHITECTURE.md, sección "Fase
  // Contactos": refresh al cargar/al pedirlo, no en vivo).
  //
  // refreshKey es el disparador para volver a pedir la lista SIN sacar la
  // función de carga fuera del efecto -- regla de pureza de React 19
  // (react-hooks/set-state-in-effect): el linter solo puede confirmar que
  // ningún setState corre de forma sincrónica si la función async está
  // DEFINIDA DENTRO del efecto (con el await como primera línea); una
  // función de carga a nivel de componente, aunque también empiece con
  // await, no la puede rastrear -- mismo patrón que loadConversations en
  // ConversationSidebar.tsx, extendido con el refetch-por-dependencia que
  // ya usa el resto del proyecto para "volver a correr un efecto a pedido".
  useEffect(() => {
    let active = true;

    async function fetchContacts() {
      const { data, error } = await supabase
        .from("contacts")
        .select(CONTACT_SELECT)
        .order("created_at", { ascending: false, foreignTable: "conversations" })
        .limit(1, { foreignTable: "conversations" })
        .order("created_at", { ascending: false })
        .limit(CONTACT_LIST_LIMIT);

      if (!active) return;
      if (error) {
        console.error("Error cargando contactos:", error.message);
        setLoadError("No se pudieron cargar los contactos.");
      } else {
        setLoadError(null);
        setContacts((data ?? []) as ContactWithConversation[]);
      }
      setLoadingList(false);
    }

    fetchContacts();

    return () => {
      active = false;
    };
  }, [refreshKey]);

  function refresh() {
    setLoadingList(true);
    setRefreshKey((k) => k + 1);
  }

  // Búsqueda server-side, debounced. Los operadores `.or()` de PostgREST
  // separan condiciones por "," y columna/operador/valor por "." -- se
  // limpian esos caracteres del término de búsqueda para que no rompan (ni
  // reinterpreten) la sintaxis del filtro. No es una defensa de inyección
  // SQL (PostgREST ya parametriza los valores) -- es solo para que un
  // usuario que busca "3001234567," no reciba un error de sintaxis.
  // Nada que hacer si no hay termino -- `displayed` ya usa `contacts` en ese
  // caso (ver mas abajo), no hace falta limpiar searchResults/searchError
  // desde aca. Evita a proposito cualquier setState SINCRONICO en el cuerpo
  // del efecto (regla de pureza de React 19, react-hooks/set-state-in-effect)
  // -- setSearching(true) vive DENTRO del callback del setTimeout, no antes,
  // por la misma razon. Si el usuario borra la busqueda o escribe algo nuevo
  // antes de que el timer dispare, el cleanup cancela el timer y el guard
  // `active` descarta una respuesta que ya no corresponde al termino actual
  // -- un `searching`/`searchResults` que queda "pisado" en ese abandono es
  // inofensivo porque `isSearching` (derivado del `search` VIVO, no del
  // closure de este efecto) ya dejo de leerlos.
  useEffect(() => {
    const q = search.trim();
    if (!q) return;

    let active = true;
    const safe = q.replace(/[,()]/g, "");

    const timer = setTimeout(async () => {
      setSearching(true);
      const { data, error } = await supabase
        .from("contacts")
        .select(CONTACT_SELECT)
        .order("created_at", { ascending: false, foreignTable: "conversations" })
        .limit(1, { foreignTable: "conversations" })
        .or(
          `name.ilike.%${safe}%,phone.ilike.%${safe}%,email.ilike.%${safe}%,company.ilike.%${safe}%`
        )
        .order("created_at", { ascending: false })
        .limit(SEARCH_RESULT_LIMIT);

      if (!active) return;
      if (error) {
        console.error("Error buscando contactos:", error.message);
        setSearchError("No se pudo completar la búsqueda.");
        setSearchResults([]);
      } else {
        setSearchError(null);
        setSearchResults((data ?? []) as ContactWithConversation[]);
      }
      setSearching(false);
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [search]);

  const isSearching = search.trim().length > 0;
  // isSearching decide, no la sola presencia de searchResults -- un
  // searchResults "viejo" (de la ultima busqueda antes de borrar el campo)
  // no debe seguir mostrandose una vez que isSearching vuelve a false.
  const displayed = isSearching ? searchResults ?? [] : contacts;

  function openContact(contact: ContactWithConversation) {
    const conversationId = contact.conversations?.[0]?.id;
    if (conversationId) {
      router.push(`/conversations/${conversationId}`);
    }
  }

  function openForm() {
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  }

  function closeForm() {
    if (savingRef.current) return; // no cerrar a mitad de un guardado en vuelo
    setFormOpen(false);
  }

  async function handleCreateContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accountId || savingRef.current) return;

    const phone = normalizePhone(form.phone);
    // 10-15 dígitos: E.164 (código de país + número) va de ~10 a 15 dígitos
    // en total. length>=8 dejaba pasar números SIN código de país (Perú: 9
    // dígitos, Colombia: 10) -- ese contacto nunca calza con el wa_id real
    // que manda Meta (que sí lleva código de país), y el relay termina
    // creando un segundo contacto duplicado la primera vez que esa persona
    // le escribe de verdad al agente.
    if (phone.length < 10 || phone.length > 15) {
      setFormError(
        "El teléfono debe incluir el código de país (ej. 51987654321 para Perú, 573001234567 para Colombia) -- entre 10 y 15 dígitos."
      );
      return;
    }

    savingRef.current = true;
    setSaving(true);
    setFormError(null);

    const { error } = await supabase.from("contacts").insert({
      account_id: accountId,
      phone,
      name: form.name.trim() || null,
      email: form.email.trim() || null,
      company: form.company.trim() || null,
    });

    savingRef.current = false;
    setSaving(false);

    if (error) {
      // 23505 = unique_violation -- ya existe un contacto con ese
      // (account_id, phone) por el constraint de 001_initial_schema.sql.
      setFormError(
        error.code === "23505"
          ? "Ya existe un contacto con ese teléfono."
          : "No se pudo guardar el contacto."
      );
      return;
    }

    setFormOpen(false);
    refresh();
  }

  if (loadingSession) {
    return null;
  }

  const accountUnresolved = !accountId;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-wa-list-bg">
      <header className="flex items-center justify-between border-b border-wa-border bg-wa-header px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Contactos</h1>
          <p className="text-sm text-wa-text-secondary">
            {isSearching
              ? searching
                ? "Buscando..."
                : `${displayed.length} resultado${displayed.length === 1 ? "" : "s"} para "${search.trim()}"`
              : contacts.length >= CONTACT_LIST_LIMIT
                ? `Mostrando los ${contacts.length} más recientes.`
                : `${contacts.length} contacto${contacts.length === 1 ? "" : "s"} en total.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {accountUnresolved && (
            <span className="text-xs text-red-600 dark:text-red-400">
              No se pudo resolver tu cuenta -- recarga la página.
            </span>
          )}
          <button
            onClick={refresh}
            disabled={loadingList}
            title="Refrescar"
            className="rounded border border-wa-border px-3 py-2 text-sm text-wa-text-secondary hover:bg-wa-hover disabled:opacity-50"
          >
            ↻
          </button>
          <button
            onClick={openForm}
            disabled={accountUnresolved}
            className="rounded bg-wa-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            + Agregar contacto
          </button>
        </div>
      </header>

      <div className="border-b border-wa-border px-6 py-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar por nombre, teléfono, email o empresa..."
          className="w-full max-w-sm rounded-lg bg-wa-hover px-3 py-1.5 text-sm text-foreground placeholder:text-wa-text-secondary focus:outline-none"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-2">
        {loadingList ? (
          <p className="py-6 text-sm text-wa-text-secondary">Cargando contactos...</p>
        ) : !isSearching && loadError ? (
          <div className="py-6">
            <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
            <button
              onClick={refresh}
              className="mt-2 text-sm text-wa-accent hover:underline"
            >
              Reintentar
            </button>
          </div>
        ) : isSearching && searchError ? (
          <p className="py-6 text-sm text-red-600 dark:text-red-400">{searchError}</p>
        ) : displayed.length === 0 ? (
          <p className="py-6 text-sm text-wa-text-secondary">
            {isSearching ? "Sin resultados para esa búsqueda." : "No hay contactos todavía."}
          </p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-wa-border text-left text-xs text-wa-text-secondary">
                <th className="py-2 pr-4 font-medium">Nombre</th>
                <th className="py-2 pr-4 font-medium">Teléfono</th>
                <th className="py-2 pr-4 font-medium">Email</th>
                <th className="py-2 pr-4 font-medium">Empresa</th>
                <th className="py-2 pr-4 font-medium">Creado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-wa-border">
              {displayed.map((c) => {
                const hasConversation = Boolean(c.conversations?.[0]?.id);
                return (
                  <tr
                    key={c.id}
                    onClick={() => openContact(c)}
                    className={
                      hasConversation
                        ? "cursor-pointer hover:bg-wa-hover"
                        : "opacity-70"
                    }
                    title={hasConversation ? "Abrir conversación" : "Sin conversación por WhatsApp todavía"}
                  >
                    <td className="py-2.5 pr-4 font-medium text-foreground">
                      {c.name || "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-wa-text-secondary">{c.phone}</td>
                    <td className="py-2.5 pr-4 text-wa-text-secondary">{c.email || "—"}</td>
                    <td className="py-2.5 pr-4 text-wa-text-secondary">{c.company || "—"}</td>
                    <td className="py-2.5 pr-4 text-wa-text-secondary">
                      {new Date(c.created_at).toLocaleDateString("es-CO")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {formOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          onClick={closeForm}
        >
          <form
            onSubmit={handleCreateContact}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-lg border border-wa-border bg-wa-list-bg p-5 shadow-lg"
          >
            <h2 className="mb-4 text-base font-semibold text-foreground">Agregar contacto</h2>

            {formError && (
              <p className="mb-3 text-xs text-red-600 dark:text-red-400">{formError}</p>
            )}

            <div className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-xs text-wa-text-secondary">
                Nombre
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="rounded border border-wa-border bg-background px-3 py-1.5 text-sm text-foreground"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-wa-text-secondary">
                Teléfono (con código de país, sin +)
                <input
                  type="text"
                  required
                  value={form.phone}
                  onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                  placeholder="51987654321"
                  className="rounded border border-wa-border bg-background px-3 py-1.5 text-sm text-foreground"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-wa-text-secondary">
                Email
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                  className="rounded border border-wa-border bg-background px-3 py-1.5 text-sm text-foreground"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-wa-text-secondary">
                Empresa
                <input
                  type="text"
                  value={form.company}
                  onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
                  className="rounded border border-wa-border bg-background px-3 py-1.5 text-sm text-foreground"
                />
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeForm}
                disabled={saving}
                className="rounded border border-wa-border px-3 py-1.5 text-xs font-medium text-wa-text-secondary disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={saving}
                className="rounded bg-wa-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {saving ? "Guardando..." : "Guardar"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
