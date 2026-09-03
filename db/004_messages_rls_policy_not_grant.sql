-- ============================================================================
-- 004 — Cerrar el hueco de escritura en `messages` via policy, no via grant
-- ============================================================================
-- Diagnostico real (2026-08-07, verificado con information_schema.table_privileges
-- incluyendo la columna grantor -- no alcanza con mirar solo privilege_type):
-- el REVOKE de 003_tighten_rls.sql limpio los grants que el propio rol
-- `postgres` habia otorgado, pero NO pudo tocar un grant SEPARADO de
-- INSERT/SELECT/UPDATE sobre `messages` a `authenticated` cuyo grantor es
-- `supabase_realtime_admin` -- otorgado automaticamente por Supabase al
-- agregar la tabla a la publicacion `supabase_realtime` (migracion 001) o al
-- habilitar Realtime desde el Table Editor. `postgres` no tiene autoridad
-- para revocar un grant que no otorgo el mismo salvo ser dueno del objeto
-- con privilegio explicito sobre ESE grant puntual -- el REVOKE corrio sin
-- error, simplemente no alcanzo esas filas. Confirmado pegando el resultado
-- con `grantor` incluido, no solo `privilege_type` (ahi se veia "SELECT"
-- duplicado y quedaban INSERT/UPDATE, que es justo la firma de este problema).
--
-- Persiguiendo el grant no se puede desde aca (requeriria privilegios de
-- `supabase_realtime_admin`, que el SQL Editor no da). Se cierra por el lado
-- que si controlamos: la policy RLS. Con row level security activo, un
-- comando SIN ninguna policy permisiva aplicable se deniega SIEMPRE, sin
-- importar que el grant de tabla lo permita -- el grant fantasma de
-- supabase_realtime_admin queda inofensivo (INSERT/UPDATE lo va a rechazar
-- RLS, aunque el grant diga que si se puede intentar).
--
-- El relay NUNCA se ve afectado: usa la service_role key, que salta RLS por
-- completo (ver docstring de supabase_client.py) -- sigue pudiendo insertar
-- mensajes normalmente.

begin;

drop policy if exists msg_members on messages;

create policy msg_select on messages
  for select using (is_member_of(account_id));

-- Mismo criterio en conversations por consistencia y defensa en profundidad:
-- ahi el REVOKE de 003 SI funciono limpio (confirmado, sin grantor extra),
-- pero la policy "for all" seguia siendo mas permisiva de lo que hace falta.
-- Reemplazada por policies explicitas por comando -- select para todos los
-- miembros, update solo para lo que la Fase 7 necesita (el grant de columna
-- de 003, que si funciono, sigue limitando A QUE COLUMNAS alcanza ese update).
drop policy if exists conv_members on conversations;

create policy conv_select on conversations
  for select using (is_member_of(account_id));

create policy conv_update_gate on conversations
  for update using (is_member_of(account_id)) with check (is_member_of(account_id));

commit;
