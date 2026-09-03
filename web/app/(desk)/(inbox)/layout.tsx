import ConversationSidebar from "@/components/ConversationSidebar";

// Extraido de app/(desk)/layout.tsx (Fase Contactos, 2026-08-10) -- el
// sidebar de conversaciones ahora es especifico de "/" y
// "/conversations/[id]", no de toda la bandeja. "(inbox)" es otro route
// group invisible en la URL, anidado dentro de "(desk)": el layout de arriba
// ya resolvio el gate de sesion y renderiza el NavRail; este solo agrega el
// sidebar de conversaciones para las rutas que de verdad lo necesitan --
// "/contacts" (fuera de este grupo) no lo monta.
export default function InboxLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 overflow-hidden">
      <ConversationSidebar />
      <div className="flex flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  );
}
