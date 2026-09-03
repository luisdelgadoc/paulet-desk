-- ============================================================================
-- Fix hallado en revision de la Fase 2 (2026-08-06): conversaciones duplicadas
-- ============================================================================
-- find_or_create_open_conversation hace GET, y si no encuentra, POST -- entre
-- esos dos hay un await. Sin un constraint que lo impida, dos mensajes casi
-- simultaneos del mismo contacto (WhatsApp los manda seguido) pueden crear
-- DOS conversaciones "open" para el mismo contacto.
--
-- Por que esto es grave y no solo un detalle: en la Fase 7 (gate de
-- human-in-the-loop), el relay busca "la conversacion open mas reciente" para
-- decidir si el agente debe responder. Si hay dos conversaciones open, un humano
-- puede tomar el control de una (assigned_to en la fila A) mientras el
-- siguiente mensaje del cliente se engancha silenciosamente a la fila B --
-- que no tiene assigned_to. El gate falla sin ningun error visible, y el agente
-- le responde encima del humano. Exactamente el bug que este diseño existe
-- para evitar.
--
-- La regla de negocio real es "un contacto tiene a lo sumo una conversacion
-- open a la vez" -- eso es representable como un indice unico parcial.
-- ============================================================================

begin;

create unique index conversations_one_open_per_contact
  on conversations (account_id, contact_id)
  where status = 'open';

commit;
