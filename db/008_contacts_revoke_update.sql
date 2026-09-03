-- ============================================================================
-- 008 — Revocar UPDATE de contacts: ningún flujo lo usa todavía
-- ============================================================================
-- Hallazgo de la revisión de una revisión posterior de la Fase Contactos (2026-08-10): 007
-- abrió `cont_update` + `grant update (name, email, company)` con el
-- comentario "esa UI real llega ahora (alta manual de contactos + edicion de
-- email/company)" -- la segunda mitad era falsa. desk/web/app/(desk)/contacts/
-- solo tiene el modal de ALTA; no hay un solo `.update()` sobre `contacts` en
-- toda la web. Decisión explícita del usuario (2026-08-10): no se construye
-- edición de contactos por ahora -- así que esto es exactamente el mismo
-- diagnóstico que motivó 006 (`conversations.status`: "superficie de
-- escritura que no corresponde a ningún flujo real -- exactamente el tipo de
-- cosa que el lineamiento de 'orden, estructura, consistencia' pide cerrar
-- apenas se detecta, no dejar para después").
--
-- Motivo extra para cerrarlo ahora y no "dejarlo por si acaso": a diferencia
-- de `messages` (004), la RLS de `contacts` en 007 depende del GRANT de
-- columna para que `phone`/`custom_fields` queden fuera del UPDATE -- la
-- policy en sí (`with check (is_member_of(account_id))`) no distingue
-- columnas. Si `contacts` entra alguna vez a la publicación
-- `supabase_realtime` (hoy no está, ver 001_initial_schema.sql), Supabase
-- puede otorgar UPDATE con grantor `supabase_realtime_admin` -- grant que
-- `postgres` NO puede revocar (lección real de 004) -- y en ese escenario
-- `phone`/`custom_fields` quedarían escribibles desde el navegador SIN que
-- `pg_policies` lo delate (las policies "explícitas" seguirían viéndose
-- igual). Sin ninguna policy permisiva de UPDATE, ese grant fantasma queda
-- inofensivo pase lo que pase -- mismo mecanismo que ya protege a `messages`.
--
-- Si en el futuro se construye edición real de contactos, se reabre a
-- propósito en una migración nueva, con su UI real detrás -- no antes.

begin;

drop policy if exists cont_update on contacts;

revoke update on contacts from authenticated;

commit;
