// Antes esta ruta ("/") era la lista completa de conversaciones (Fase 6).
// Ahora la lista vive siempre visible en el sidebar del layout compartido
// (ver app/(desk)/(inbox)/layout.tsx) -- esta pagina es lo que se ve en el panel
// derecho cuando todavia no se eligio ninguna conversacion. Sin hooks, sin
// "use client": no necesita nada interactivo, el gate de sesion ya lo
// resolvio el layout antes de que esto se monte.
export default function ConversationEmptyState() {
  return (
    <div className="flex flex-1 items-center justify-center bg-wa-chat-bg">
      <p className="text-sm text-wa-text-secondary">
        Selecciona una conversación para ver los mensajes.
      </p>
    </div>
  );
}
