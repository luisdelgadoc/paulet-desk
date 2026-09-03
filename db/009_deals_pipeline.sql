-- ============================================================================
-- 009 — Pipeline de relación con el cliente: deal_stages + deals
-- ============================================================================
-- Diseño acordado con el usuario (ver las notas de arquitectura, "Plan acordado: Dashboard,
-- Contactos y Pipeline"): un ciclo de vida de CLIENTE, editable por cuenta,
-- con 6 etapas por defecto (Lead → Cotizado → Agendado → Finalizado →
-- Recurrente → Perdido). NO es el objeto "turno/booking" que ya tiene su
-- propio lugar reservado en `pipelines`/`pipeline_stages`/`bookings` desde
-- 001_initial_schema.sql -- esas tablas quedan intactas, para cuando se
-- migre el Sheet de Turnos del agente (trabajo futuro aparte, documentado en
-- las notas de arquitectura). Mezclar los dos conceptos en la misma tabla hubiera hecho que
-- una etapa "Lead" apareciera junto a columnas de `fecha`/`ninera_asignada`/
-- `sheet_row` que no tienen ningún sentido ahí -- exactamente el tipo de
-- confusión que este proyecto viene corrigiendo activamente en su propia
-- revisión de código (ver Fase Contactos).
--
-- Un solo pipeline por cuenta (no multi-pipeline) -- por eso no hace falta
-- una tabla `pipelines` propia acá: `deal_stages.account_id` alcanza.

begin;

create table deal_stages (
  id              uuid primary key default gen_random_uuid(),
  account_id      uuid not null references accounts(id) on delete cascade,
  name            text not null,
  position        int not null default 0,
  color           text not null default '#6b7280',
  -- Exactamente UNA etapa "de entrada" por cuenta -- ahí se crea el deal
  -- automático de un contacto nuevo (ver trigger más abajo). Enforced con un
  -- índice único parcial, mismo patrón que la conversación abierta única de
  -- 002_conversations_unique_open.sql -- no confiar en que la aplicación
  -- nunca se equivoque, que el propio Postgres lo impida.
  is_entry_stage  boolean not null default false,
  created_at      timestamptz not null default now(),
  unique (account_id, name)
);

create index deal_stages_account_idx on deal_stages (account_id, position);

create unique index deal_stages_one_entry_per_account
  on deal_stages (account_id)
  where is_entry_stage;

create table deals (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references accounts(id) on delete cascade,
  contact_id  uuid not null references contacts(id) on delete cascade,
  -- on delete restrict, no cascade: borrar una etapa con deals adentro debe
  -- fallar ruidosamente, no dejar deals huérfanos en silencio. No hay UI
  -- para borrar etapas todavía, así que esto no muerde hoy -- pero si
  -- alguien lo hace a mano desde el SQL Editor, mejor un error claro.
  stage_id    uuid not null references deal_stages(id) on delete restrict,
  value_cop   numeric,
  notes       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  -- "Un deal por contacto, siempre" (decisión explícita del usuario,
  -- 2026-08-10): el Kanban muestra el estado ACTUAL de la relación con cada
  -- contacto, no cada transacción. Al llegar a "Finalizado" y el contacto
  -- reserva de nuevo, ese MISMO deal se mueve a "Recurrente" -- no se crea
  -- uno nuevo.
  unique (account_id, contact_id)
);

create index deals_account_stage_idx on deals (account_id, stage_id);

-- ============================================================================
-- Semilla reusable de las 6 etapas por defecto -- pensada para volver a
-- llamarse cuando se dé de alta un cliente nuevo de Paulet Desk (ver
-- skill paulet-desk-onboarding), no solo para esta migración. Los colores
-- son solo una primera pasada visual, no una decisión de producto.
-- ============================================================================
create or replace function seed_default_deal_stages(target_account uuid)
returns void language plpgsql security definer set search_path = public as $$
begin
  insert into deal_stages (account_id, name, position, color, is_entry_stage) values
    (target_account, 'Lead',                          1, '#3b82f6', true),
    (target_account, 'Cotizado',                       2, '#f59e0b', false),
    (target_account, 'Agendado',                        3, '#8b5cf6', false),
    (target_account, 'Finalizado',                      4, '#10b981', false),
    (target_account, 'Recurrente',                      5, '#06b6d4', false),
    (target_account, 'Perdido (Cotización Rechazada)',  6, '#ef4444', false)
  on conflict (account_id, name) do nothing;
end;
$$;

-- ============================================================================
-- Auto-creación del Lead: un trigger en `contacts`, no un cambio en el relay
-- ============================================================================
-- Decisión de diseño real (no solo conveniencia): un trigger AFTER INSERT en
-- `contacts` cubre AMBOS caminos de creación de un contacto -- el del relay
-- (find_or_create_contact, con service_role, cuando un cliente nuevo le
-- escribe al agente por primera vez) Y el alta manual desde
-- desk/web/app/(desk)/contacts/ (INSERT del navegador, con RLS) -- con un
-- solo mecanismo, en un solo lugar. Tocar el relay en Python hubiera cubierto
-- solo el primer camino; el alta manual se hubiera quedado sin su deal
-- automático, rompiendo el "siempre" de "un deal por contacto, siempre".
-- Fallo silencioso a propósito si la cuenta todavía no tiene una etapa de
-- entrada configurada (ej. justo después de crear la cuenta, antes de correr
-- seed_default_deal_stages) -- mismo criterio que el resto del proyecto para
-- fallos no críticos (ver el plugin inject-handoff-context de Hermes).
create or replace function seed_deal_for_new_contact()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  entry_stage uuid;
begin
  select id into entry_stage from deal_stages
    where account_id = new.account_id and is_entry_stage
    limit 1;

  if entry_stage is not null then
    insert into deals (account_id, contact_id, stage_id)
    values (new.account_id, new.id, entry_stage)
    on conflict (account_id, contact_id) do nothing;
  end if;

  return new;
end;
$$;

create trigger on_contact_created_seed_deal
  after insert on contacts
  for each row execute function seed_deal_for_new_contact();

-- ============================================================================
-- Backfill: cuentas y contactos que ya existían antes de esta migración
-- ============================================================================
-- El trigger de arriba solo dispara para INSERTs nuevos -- sin esto, los
-- contactos de prueba que ya existen (Luis D., Lucho D., etc.) se quedarían
-- sin deal para siempre, y el Kanban se vería vacío al probarlo hoy.
select seed_default_deal_stages(id) from accounts;

insert into deals (account_id, contact_id, stage_id)
select c.account_id, c.id, ds.id
from contacts c
join deal_stages ds on ds.account_id = c.account_id and ds.is_entry_stage
on conflict (account_id, contact_id) do nothing;

-- ============================================================================
-- RLS
-- ============================================================================
-- Nota a propósito: ninguna de las 2 tablas se agrega a la publicación
-- `supabase_realtime` -- mismo criterio ya aplicado a `contacts` (refresh al
-- cargar/al pedirlo, no en vivo) y
-- evita de raíz el mecanismo de grant fantasma de `supabase_realtime_admin`
-- que ya mordió a este proyecto en `messages` (004). Si el Kanban necesita
-- verse en vivo entre varios miembros del equipo algún día, evaluarlo
-- entonces -- no antes.
-- deal_stages: SOLO lectura desde el navegador en v1 -- no hay UI todavía
-- para agregar/renombrar/reordenar etapas (se gestionan por SQL Editor por
-- ahora). Aplicando la lección de 006/008 desde el primer día en vez de
-- después de una revisión: no abrir un grant sin un flujo real detrás.
alter table deal_stages enable row level security;

create policy deal_stages_select on deal_stages
  for select using (is_member_of(account_id));

revoke all on deal_stages from authenticated;
grant select on deal_stages to authenticated;

-- deals: el navegador puede leer todo y mover una tarjeta de etapa (drag-
-- and-drop) -- nada más. value_cop/notes quedan fuera del UPDATE a
-- propósito: no hay UI para editarlos en v1 (mismo criterio exacto que
-- 008 con contacts -- no abrir superficie sin flujo real). account_id/
-- contact_id nunca son escribibles desde el navegador (identidad del deal,
-- no algo que la UI deba poder cambiar).
alter table deals enable row level security;

create policy deals_select on deals
  for select using (is_member_of(account_id));

create policy deals_update_stage on deals
  for update using (is_member_of(account_id)) with check (is_member_of(account_id));

revoke all on deals from authenticated;
grant select on deals to authenticated;
grant update (stage_id) on deals to authenticated;

commit;
