-- ============================================================================
-- 010 — Renombrar la etapa "Perdido (Cotización Rechazada)" a solo "Perdido"
-- ============================================================================
-- Pedido del usuario tras ver el Kanban real (2026-08-10): el nombre largo
-- no dejaba ver la columna "Perdido" completa en pantalla (ver también el
-- ancho de columna reducido en app/(desk)/pipeline/page.tsx, w-64 -> w-40).
--
-- El nombre vive en datos (deal_stages.name), no en código -- no alcanza con
-- cambiar la UI. Se actualiza la función de semilla (para que cuentas
-- nuevas ya se creen con el nombre corto) y se renombra la fila ya sembrada
-- de las cuentas existentes.

begin;

create or replace function seed_default_deal_stages(target_account uuid)
returns void language plpgsql security definer set search_path = public as $$
begin
  insert into deal_stages (account_id, name, position, color, is_entry_stage) values
    (target_account, 'Lead',       1, '#3b82f6', true),
    (target_account, 'Cotizado',   2, '#f59e0b', false),
    (target_account, 'Agendado',   3, '#8b5cf6', false),
    (target_account, 'Finalizado', 4, '#10b981', false),
    (target_account, 'Recurrente', 5, '#06b6d4', false),
    (target_account, 'Perdido',    6, '#ef4444', false)
  on conflict (account_id, name) do nothing;
end;
$$;

update deal_stages set name = 'Perdido' where name = 'Perdido (Cotización Rechazada)';

commit;
