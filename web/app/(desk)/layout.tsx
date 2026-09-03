"use client";

import { useRequireSession } from "@/lib/useRequireSession";
import NavRail from "@/components/NavRail";

// Reemplaza a las 2 paginas separadas que existian antes (lista en "/",
// hilo en "/conversations/[id]", con un <Link> de ida y vuelta entre las
// dos). Pedido explicito del usuario, 2026-08-08: una sola interfaz, lista
// siempre visible a la izquierda, detalle a la derecha -- como
// WhatsApp Web. El "(desk)" del nombre de la carpeta es un route group de
// Next.js: no aparece en la URL, solo agrupa TODAS las secciones protegidas
// bajo este layout compartido sin afectar las rutas. "/login" queda AFUERA
// del grupo a proposito -- no debe llevar navegacion.
//
// El gate de sesion (redirect a /login si no hay usuario) bloquea el
// montaje del layout completo aca -- pero OJO, cada page hija (contacts,
// el hilo de conversacion) sigue llamando useRequireSession() por su
// cuenta para leer accountId/loading -- no es una unica resolucion
// compartida via Context, son varias instancias del mismo hook que
// coinciden en el resultado (cacheado por userId, ver useRequireSession.ts).
// Lo que SI se centraliza aca es el redirect: si no hay sesion, ninguna
// pagina hija llega a montarse para volver a repetirlo.
//
// Fase Contactos (2026-08-10): este layout ya NO monta ConversationSidebar
// directo -- eso ahora vive en app/(desk)/(inbox)/layout.tsx, especifico de
// las rutas de conversaciones. Aca solo va el NavRail, comun a TODAS las
// secciones ("/", "/conversations/[id]", "/contacts", y las que se agreguen
// despues -- Pipeline, Dashboard).
export default function DeskLayout({ children }: { children: React.ReactNode }) {
  const { userId, loading } = useRequireSession();

  if (loading || !userId) {
    return null;
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <NavRail />
      <div className="flex flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
