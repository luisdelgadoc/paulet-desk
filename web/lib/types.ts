// Espejo minimo de desk/db/*.sql -- solo los campos que la bandeja usa hoy.
// Si el esquema de Supabase cambia, este es el unico lugar que hay que
// actualizar en el front -- no repetir estas formas sueltas en cada
// page.tsx. Ya no es "solo lectura" desde la Fase Contactos (2026-08-07):
// contacts admite alta manual (INSERT) desde app/(desk)/contacts/.

export type ConversationStatus = "open" | "closed";
export type MessageDirection = "inbound" | "outbound";
export type MessageSender = "customer" | "bot" | "human";
export type MessageStatus = "pending" | "sent" | "delivered" | "read" | "failed";

export interface Contact {
  id: string;
  account_id: string;
  phone: string;
  name: string | null;
  email: string | null;
  company: string | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  account_id: string;
  contact_id: string;
  status: ConversationStatus;
  // NULL = el agente esta a cargo. No-NULL = un humano tomo el control.
  // El boton para cambiar esto es Fase 7 -- aqui solo se lee y se muestra.
  assigned_to: string | null;
  assigned_at: string | null;
  handoff_context_pending: string | null;
  last_message_at: string | null;
  created_at: string;
}

// El preview del ultimo mensaje en la lista (barra lateral) viaja embebido
// en la misma query de conversations via PostgREST (select=*,messages(...))
// con order+limit aplicado AL EMBED, no a la tabla principal -- por eso es
// un array de a lo sumo 1 elemento, no un objeto suelto. Ver
// ConversationSidebar.tsx para la query exacta. Verificado contra Supabase
// real (2026-08-08) antes de escribir esto: el embed con
// .order(..., { foreignTable: "messages" }).limit(1, { foreignTable: "messages" })
// efectivamente devuelve solo el mensaje mas reciente por conversacion.
export interface ConversationWithContact extends Conversation {
  contacts: Contact | null;
  messages?: Pick<Message, "body" | "type" | "created_at">[] | null;
}

// El embed reverso de "conversations" (contacts es el lado "uno" de la
// relacion, conversations el lado "muchos") con order+limit aplicados AL
// EMBED trae la conversacion mas reciente de cada contacto en la misma
// consulta -- mismo patron ya verificado contra Supabase real para el
// preview de ultimo mensaje de ConversationWithContact de arriba. Ver
// app/(desk)/contacts/page.tsx para la query exacta. Se usa solo para saber
// A DONDE navegar al hacer click en una fila -- un contacto cargado a mano
// que todavia no escribio por WhatsApp no tiene ninguna, y la fila
// simplemente no es clickeable.
export interface ContactWithConversation extends Contact {
  conversations?: { id: string }[] | null;
}

// Pipeline (Fase Pipeline, 2026-08-10) -- ver desk/db/009_deals_pipeline.sql
// y ARCHITECTURE.md ("Plan acordado: Dashboard, Contactos y Pipeline") para el
// diseño completo. Un solo pipeline por cuenta (no hay tabla `pipelines`
// propia -- deal_stages.account_id alcanza).
export interface DealStage {
  id: string;
  account_id: string;
  name: string;
  position: number;
  color: string;
  is_entry_stage: boolean;
  // Fase revisión Pipeline+Dashboard (2026-08-10): exactamente una etapa por
  // cuenta, índice único parcial (ver 011_deals_lost_stage_and_value.sql).
  // El Dashboard resta su valor del "Pipeline abierto" y lo muestra aparte
  // como "Valor perdido" -- no se infiere del nombre "Perdido" (las etapas
  // son editables, un match por texto se rompería en silencio si se
  // renombra).
  is_lost_stage: boolean;
  created_at: string;
}

export interface Deal {
  id: string;
  account_id: string;
  contact_id: string;
  stage_id: string;
  value_cop: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// Embed hacia adelante (deals -> contacts, FK directa) para mostrar
// nombre/telefono en cada tarjeta del Kanban sin una consulta aparte por
// deal.
export interface DealWithContact extends Deal {
  contacts: Pick<Contact, "id" | "name" | "phone"> | null;
}

export interface Message {
  id: string;
  account_id: string;
  conversation_id: string;
  wamid: string | null;
  direction: MessageDirection;
  sender: MessageSender;
  sender_user_id: string | null;
  type: string;
  body: string | null;
  media_url: string | null;
  media_mime: string | null;
  status: MessageStatus;
  error: string | null;
  created_at: string;
}
