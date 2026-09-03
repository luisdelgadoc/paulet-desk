"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./supabase";

// Gate de UI para las paginas protegidas de la bandeja (lista, hilo). La
// seguridad real vive en las policies RLS de Supabase (is_member_of) -- esto
// solo evita el parpadeo de datos vacios y redirige a /login cuando no hay
// sesion, en un solo lugar en vez de repetir el mismo useEffect en cada page.
//
// Devuelve userId (string estable), no el objeto Session completo, a
// proposito -- hallazgo de la revision conjunta Fase 5+6: Supabase dispara
// onAuthStateChange en INITIAL_SESSION y en cada TOKEN_REFRESHED (~cada
// hora) con un objeto Session NUEVO aunque sea el mismo usuario. Las paginas
// usan esto como dependencia de su propio useEffect (para cargar datos y
// suscribirse a Realtime) -- si dependieran del objeto Session, cada
// refresh de token reiniciaria esas suscripciones sin necesidad.
//
// accountId (Fase Contactos, 2026-08-10): a diferencia de las lecturas
// (Inbox), el alta manual de contactos hace un INSERT desde el navegador --
// y la policy cont_insert exige que el payload traiga un account_id del que
// el usuario sea miembro (ver desk/db/007). Asume una membresia por usuario
// (unico caso real hoy, Demo) -- si algun dia un usuario pertenece a mas
// de una cuenta, esto hay que resolverlo con un selector de cuenta activa;
// mientras tanto se detecta y se rehusa a adivinar (ver mas abajo), no se
// elige una fila al azar.
//
// Cache de modulo por userId: este hook NO es un Context -- cada componente
// que lo llama (layout, ContactsPage, la pagina del hilo) dispara su PROPIA
// instancia con su propio efecto. Sin cachear, navegar de "/" a "/contacts"
// remonta un useRequireSession nuevo que vuelve a pedir la sesion Y a
// consultar memberships de cero, aunque el layout de arriba ya lo haya
// resuelto segundos antes -- round-trip doblado y parpadeo en blanco en
// cada navegacion. El cache es solo de valor (no de promesa en vuelo), asi
// que el primer montaje de la sesion puede seguir disparando 2 consultas en
// paralelo si dos hooks se montan a la vez -- resolver eso del todo pediria
// subir el estado a un Context, que es mas de lo que hace falta aca.
const accountIdCache = new Map<string, string | null>();

// Hallazgo de la revision de la Fase Contactos (una revisión posterior): con la version
// anterior, `applySession` era async y el early-return ("ya estoy resolviendo
// este mismo usuario") tambien terminaba la promesa de inmediato -- si
// onAuthStateChange disparaba INITIAL_SESSION ANTES de que resolviera
// getSession() (orden real, no hipotetico), el camino de getSession() veia
// "mismo userId, nada que hacer" y su `.then(() => setLoading(false))`
// corria YA, mientras la consulta a memberships del otro camino seguia en
// vuelo -- loading llegaba a false con accountId todavia en null.
//
// Arreglo: applySession pasa a ser SINCRONICA. Si el userId no cambio, no
// hace nada (ni toca loading). Si cambio, dispara resolveAccount() con un
// requestId propio, y es la PROPIA resolucion (no el caller) la que decide
// cuando loading pasa a false -- comparando requestId contra la ultima
// solicitud disparada, asi una resolucion vieja que resuelve tarde nunca
// pisa el resultado de una mas nueva.
export function useRequireSession() {
  const router = useRouter();
  const [userId, setUserId] = useState<string | null>(null);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const currentUserId = useRef<string | null>(null);
  const latestRequestId = useRef(0);

  useEffect(() => {
    let active = true;

    async function resolveAccount(uid: string, requestId: number) {
      if (accountIdCache.has(uid)) {
        return accountIdCache.get(uid) ?? null;
      }

      // .order() para que el resultado sea deterministico si algun dia hay
      // mas de una fila -- sin esto, PostgREST puede devolver una fila
      // distinta entre recargas. limit(2), no 1: para PODER detectar "hay
      // mas de una" en vez de silenciosamente quedarnos con la primera que
      // llegue.
      const { data, error } = await supabase
        .from("memberships")
        .select("account_id")
        .eq("user_id", uid)
        .order("created_at", { ascending: true })
        .limit(2);

      if (!active || requestId !== latestRequestId.current) return null;

      if (error) {
        console.error("Error resolviendo account_id:", error.message);
        return null;
      }
      if (!data || data.length === 0) {
        return null;
      }
      if (data.length > 1) {
        // No adivinar. Un usuario con mas de una membresia es un caso real
        // que este hook todavia no soporta (ver comentario de arriba) --
        // mejor accountId=null (bloquea el INSERT con un mensaje claro) que
        // insertar en la cuenta equivocada sin que nadie se entere.
        console.error(
          `Usuario ${uid} pertenece a más de una cuenta -- no soportado todavía, se necesita un selector de cuenta activa.`
        );
        return null;
      }

      const resolved = data[0].account_id as string;
      accountIdCache.set(uid, resolved);
      return resolved;
    }

    function applySession(session: Session | null) {
      const nextUserId = session?.user.id ?? null;
      if (!nextUserId) {
        router.replace("/login");
        if (active) setLoading(false);
        return;
      }
      if (nextUserId === currentUserId.current) {
        // Ya en curso o ya resuelto para este userId -- no reiniciar nada.
        return;
      }
      currentUserId.current = nextUserId;
      setUserId(nextUserId);
      setAccountId(null);

      latestRequestId.current += 1;
      const requestId = latestRequestId.current;
      resolveAccount(nextUserId, requestId).then((resolved) => {
        if (!active || requestId !== latestRequestId.current) return;
        setAccountId(resolved);
        setLoading(false);
      });
    }

    supabase.auth.getSession().then(({ data }) => applySession(data.session));

    const { data: listener } = supabase.auth.onAuthStateChange(
      (_event, newSession) => {
        applySession(newSession);
      }
    );

    return () => {
      active = false;
      listener.subscription.unsubscribe();
    };
  }, [router]);

  return { userId, accountId, loading };
}
