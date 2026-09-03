-- ============================================================================
-- 011 — is_lost_stage + edición real de value_cop + auto-touch de updated_at
-- ============================================================================
-- Hallazgos reales de la revisión conjunta de una revisión posterior sobre Pipeline+Dashboard
-- (2026-08-10):
--   🔴 Nada en todo el proyecto escribía `value_cop` -- "Valor de pipeline"
--      y el gráfico de barras por etapa siempre mostraban $0, para siempre.
--   🟡 `deals.updated_at` declarada y nunca tocada -- mentía "última
--      modificación" siendo siempre igual a `created_at`.
-- Decisión del usuario, explícita: el valor SÍ debe funcionar (se carga
-- cuando el deal llega a "Cotizado"), y si se rechaza y pasa a "Perdido" ese
-- valor debe restarse del pipeline activo -- necesita un indicador de
-- pérdida aparte en el Dashboard, no solo desaparecer del total.
--
-- Para que el Dashboard sepa CUÁL etapa es la de pérdida sin asumir el
-- nombre literal "Perdido" (las etapas son editables por cuenta -- si
-- alguien la renombra, un match por texto se rompe en silencio), se agrega
-- `is_lost_stage`, mismo patrón exacto que `is_entry_stage` de 009: un
-- booleano con un índice único parcial, no una convención de nombre.

begin;

alter table deal_stages add column if not exists is_lost_stage boolean not null default false;

create unique index deal_stages_one_lost_per_account
  on deal_stages (account_id)
  where is_lost_stage;

-- Backfill: marcar la etapa "Perdido" ya sembrada (renombrada en 010) para
-- las cuentas existentes.
update deal_stages set is_lost_stage = true where name = 'Perdido';

-- Actualiza la función de semilla para que cuentas nuevas ya se creen con
-- el flag correcto desde el día uno.
create or replace function seed_default_deal_stages(target_account uuid)
returns void language plpgsql security definer set search_path = public as $$
begin
  insert into deal_stages (account_id, name, position, color, is_entry_stage, is_lost_stage) values
    (target_account, 'Lead',       1, '#3b82f6', true,  false),
    (target_account, 'Cotizado',   2, '#f59e0b', false, false),
    (target_account, 'Agendado',   3, '#8b5cf6', false, false),
    (target_account, 'Finalizado', 4, '#10b981', false, false),
    (target_account, 'Recurrente', 5, '#06b6d4', false, false),
    (target_account, 'Perdido',    6, '#ef4444', false, true)
  on conflict (account_id, name) do nothing;
end;
$$;

-- updated_at auto-touch: cubre CUALQUIER UPDATE de deals (mover de etapa via
-- drag-and-drop, editar value_cop desde la tarjeta) con un solo mecanismo,
-- sin depender de que cada caller se acuerde de mandar updated_at a mano --
-- mismo criterio que el trigger de auto-creación de deals de 009 (un
-- invariante de base de datos, no una convención de aplicación).
create or replace function touch_deal_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger on_deal_updated_touch
  before update on deals
  for each row execute function touch_deal_updated_at();

-- Amplía el grant de columna que 009 dejó acotado a solo stage_id -- ahora
-- hay un flujo real (edición de valor en la tarjeta del Kanban) detrás.
-- notes sigue fuera a propósito: sin UI todavía, misma disciplina de no
-- abrir superficie sin flujo real.
grant update (stage_id, value_cop) on deals to authenticated;

commit;
