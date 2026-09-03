-- ============================================================================
-- 006 — Achicar el grant de columna de `conversations` a lo que la UI usa de verdad
-- ============================================================================
-- Hallazgo de la revisión de código posterior(2026-08-08): la migracion 003 le
-- dio al navegador `grant update (assigned_to, assigned_at, status) on
-- conversations to authenticated` -- pero ni el boton "Tomar
-- conversacion"/"Devolver al bot" (desk/web/app/conversations/[id]/page.tsx
-- en su momento -- esa ruta se movio a
-- desk/web/app/(desk)/(inbox)/conversations/[id]/page.tsx en la Fase
-- Contactos, 2026-08-10; se deja la ruta original acá porque es la que
-- existía cuando se escribió este hallazgo, no se reescribe el historial)
-- ni ningun Route Handler (desk/web/app/api/*) escriben la columna `status`
-- desde el navegador. La liberacion real de una conversacion pasa por
-- POST /release-conversation del relay (service_role, salta RLS) desde la
-- Fase 9 -- no por un UPDATE directo del cliente.
--
-- No es un hueco explotado hoy (el codigo del cliente nunca manda `status`
-- en su payload), pero es superficie de escritura que no corresponde a
-- ningun flujo real -- exactamente el tipo de cosa que el lineamiento de
-- "orden, estructura, consistencia" de este proyecto pide cerrar apenas se
-- detecta, no dejar para despues. Si algun dia una feature real necesita que
-- el navegador escriba `status`, agregarlo de vuelta ahi mismo, a proposito,
-- no heredado de un grant mas amplio de lo necesario.
--
-- El relay NUNCA se ve afectado: usa la service_role key, que salta grants
-- de columna y RLS por completo (ver docstring de supabase_client.py).

begin;

revoke update (status) on conversations from authenticated;

commit;
