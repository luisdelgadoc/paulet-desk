-- ============================================================================
-- Paulet Desk — esquema inicial
-- ============================================================================
-- Criterio de qué entra en esta migración y qué no:
--
--   ENTRA AHORA todo lo que otras tablas referencian o que define la pertenencia
--   de una fila (cuentas, membresías, canal, pipeline, bookings). Retrofitear eso
--   después obliga a reescribir filas y políticas RLS en toda la base.
--
--   SE DEJA PARA DESPUÉS lo puramente aditivo, que se agrega sin tocar nada
--   existente: broadcasts, plantillas de mensaje, automatizaciones, api_keys,
--   webhooks salientes, notificaciones.
--
--   FUERA DE ALCANCE por decisión del producto: base de conocimiento / búsqueda
--   semántica (lo que en wacrm es ai_knowledge).
--
-- La Fase 1 solo CONSTRUYE inbox + human-in-the-loop; las tablas de fases
-- posteriores quedan creadas pero sin uso.
-- ============================================================================

begin;

create extension if not exists pgcrypto;

-- ============================================================================
-- 1. Cuentas, usuarios y roles
-- ============================================================================
-- Multi-cuenta desde el día uno: el producto de Paulet es "un equipo de agentes
-- por negocio", así que cada negocio cliente será una fila de accounts. Para la
-- demo hay una sola (Demo), pero la columna account_id ya viaja en todo.

create table accounts (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_at  timestamptz not null default now()
);

create table profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  full_name   text,
  avatar_url  text,
  created_at  timestamptz not null default now()
);

create type member_role as enum ('owner', 'admin', 'agent');

create table memberships (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references accounts(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  role        member_role not null default 'agent',
  created_at  timestamptz not null default now(),
  unique (account_id, user_id)
);

-- Crear el profile automáticamente al registrarse un usuario.
create or replace function handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, full_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', new.email));
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- ============================================================================
-- 2. Canal de WhatsApp
-- ============================================================================
-- Las credenciales de Meta viven en el .env del relay, NO aquí. Esta tabla existe
-- para poder enrutar por phone_number_id cuando haya más de un negocio conectado.

create table channels (
  id               uuid primary key default gen_random_uuid(),
  account_id       uuid not null references accounts(id) on delete cascade,
  phone_number_id  text not null unique,   -- el de Meta
  display_phone    text,
  created_at       timestamptz not null default now()
);

-- ============================================================================
-- 3. Contactos
-- ============================================================================

create table contacts (
  id             uuid primary key default gen_random_uuid(),
  account_id     uuid not null references accounts(id) on delete cascade,
  phone          text not null,            -- normalizado E.164, sin '+'
  name           text,
  custom_fields  jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now(),
  unique (account_id, phone)
);

-- Ruta caliente del relay: llega un mensaje → buscar contacto por teléfono.
create index contacts_account_phone_idx on contacts (account_id, phone);

-- ============================================================================
-- 4. Conversaciones — aquí vive el human-in-the-loop
-- ============================================================================

create type conversation_status as enum ('open', 'closed');

create table conversations (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references accounts(id) on delete cascade,
  contact_id  uuid not null references contacts(id) on delete cascade,
  status      conversation_status not null default 'open',

  -- EL GATE. NULL = el bot (el agente) está a cargo y el relay reenvía a Hermes.
  -- No NULL = un humano tomó la conversación y el relay NO reenvía a Hermes.
  assigned_to uuid references auth.users(id) on delete set null,
  assigned_at timestamptz,

  -- Al devolver la conversación al bot se guarda aquí la transcripción de lo que
  -- habló el humano. El relay la antepone al SIGUIENTE mensaje del cliente antes
  -- de reenviarlo a Hermes, y luego limpia el campo. Sin esto, el agente retoma ciega
  -- y vuelve a pedir datos que el humano ya recolectó.
  handoff_context_pending text,

  last_message_at timestamptz,
  created_at      timestamptz not null default now()
);

create index conversations_contact_idx    on conversations (contact_id);
create index conversations_account_recent on conversations (account_id, last_message_at desc);

-- ============================================================================
-- 5. Mensajes
-- ============================================================================

create type message_direction as enum ('inbound', 'outbound');
create type message_sender    as enum ('customer', 'bot', 'human');
create type message_status    as enum ('pending', 'sent', 'delivered', 'read', 'failed');

create table messages (
  id              uuid primary key default gen_random_uuid(),
  account_id      uuid not null references accounts(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,

  -- ID del mensaje en Meta. UNIQUE es la defensa contra los reintentos del
  -- webhook: Meta reenvía si no recibe 200 rápido, y sin esto el agente respondería
  -- dos o tres veces al mismo mensaje.
  wamid           text unique,

  direction       message_direction not null,
  sender          message_sender    not null,
  sender_user_id  uuid references auth.users(id) on delete set null,  -- solo si sender='human'

  type            text not null default 'text',  -- text|audio|image|video|document|sticker|location|interactive
  body            text,
  media_url       text,
  media_mime      text,

  status          message_status not null default 'sent',
  error           text,

  created_at      timestamptz not null default now()
);

create index messages_conversation_idx on messages (conversation_id, created_at);

-- ============================================================================
-- 6. Etiquetas — FASE POSTERIOR (creadas ahora, aditivo puro)
-- ============================================================================

create table tags (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references accounts(id) on delete cascade,
  name        text not null,
  color       text not null default '#6b7280',
  created_at  timestamptz not null default now(),
  unique (account_id, name)
);

create table contact_tags (
  contact_id  uuid not null references contacts(id) on delete cascade,
  tag_id      uuid not null references tags(id) on delete cascade,
  primary key (contact_id, tag_id)
);

-- ============================================================================
-- 7. Pipeline Kanban y reservas — FASE POSTERIOR
-- ============================================================================
-- Decisión de diseño registrada: el objeto que se mueve por el pipeline es el
-- TURNO (booking), no la conversación. Hoy los turnos viven en el Google Sheet
-- "Turnos" que lee y escribe el agente; esta tabla queda creada para que migrarlos
-- después sea un cambio de una línea en su SOUL.md y no un rediseño.
-- Mientras tanto, sheet_row permite mapear cada booking a su fila del Sheet.

create table pipelines (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references accounts(id) on delete cascade,
  name        text not null,
  created_at  timestamptz not null default now()
);

create table pipeline_stages (
  id          uuid primary key default gen_random_uuid(),
  pipeline_id uuid not null references pipelines(id) on delete cascade,
  name        text not null,
  position    int  not null default 0,
  created_at  timestamptz not null default now()
);

create index pipeline_stages_pipeline_idx on pipeline_stages (pipeline_id, position);

create table bookings (
  id              uuid primary key default gen_random_uuid(),
  account_id      uuid not null references accounts(id) on delete cascade,
  contact_id      uuid references contacts(id) on delete set null,
  conversation_id uuid references conversations(id) on delete set null,
  stage_id        uuid references pipeline_stages(id) on delete set null,

  -- Espejo de las columnas del Sheet "Turnos" del agente
  turno_id        text,
  fecha           date,
  hora_inicio     time,
  hora_fin        time,
  ciudad          text,
  familia         text,
  telefono        text,
  ninera_asignada text,
  perfil          text,          -- "Estandar" | "PRO" (nombres propios, no parafrasear)
  modalidad       text,
  estado          text,          -- Pendiente | Confirmado | Completado | Cancelado
  precio_cop      numeric,
  sheet_row       int,           -- Fila_Sheet, para reconciliar con el Google Sheet

  created_at      timestamptz not null default now()
);

create index bookings_account_idx on bookings (account_id, fecha);

-- ============================================================================
-- 8. RLS
-- ============================================================================
-- El relay usa la service_role key y por diseño salta RLS. Estas políticas
-- protegen al cliente web, que usa la anon key en el navegador: sin ellas
-- cualquiera podría leer todas las conversaciones.

create or replace function is_member_of(target_account uuid)
returns boolean language sql security definer stable set search_path = public as $$
  select exists (
    select 1 from memberships m
    where m.account_id = target_account
      and m.user_id = auth.uid()
  );
$$;

alter table accounts        enable row level security;
alter table profiles        enable row level security;
alter table memberships     enable row level security;
alter table channels        enable row level security;
alter table contacts        enable row level security;
alter table conversations   enable row level security;
alter table messages        enable row level security;
alter table tags            enable row level security;
alter table contact_tags    enable row level security;
alter table pipelines       enable row level security;
alter table pipeline_stages enable row level security;
alter table bookings        enable row level security;

-- Tablas con account_id: acceso completo para miembros de esa cuenta.
create policy acct_members on accounts
  for all using (is_member_of(id)) with check (is_member_of(id));

create policy chan_members on channels
  for all using (is_member_of(account_id)) with check (is_member_of(account_id));

create policy cont_members on contacts
  for all using (is_member_of(account_id)) with check (is_member_of(account_id));

create policy conv_members on conversations
  for all using (is_member_of(account_id)) with check (is_member_of(account_id));

create policy msg_members on messages
  for all using (is_member_of(account_id)) with check (is_member_of(account_id));

create policy tag_members on tags
  for all using (is_member_of(account_id)) with check (is_member_of(account_id));

create policy pipe_members on pipelines
  for all using (is_member_of(account_id)) with check (is_member_of(account_id));

create policy book_members on bookings
  for all using (is_member_of(account_id)) with check (is_member_of(account_id));

-- Tablas sin account_id: se resuelve por su padre.
create policy ctag_members on contact_tags
  for all using (
    exists (select 1 from contacts c where c.id = contact_id and is_member_of(c.account_id))
  );

create policy stage_members on pipeline_stages
  for all using (
    exists (select 1 from pipelines p where p.id = pipeline_id and is_member_of(p.account_id))
  );

-- Cada quien ve su propio perfil y los de sus compañeros de cuenta.
create policy prof_self on profiles
  for all using (
    id = auth.uid()
    or exists (
      select 1 from memberships m1
      join memberships m2 on m1.account_id = m2.account_id
      where m1.user_id = auth.uid() and m2.user_id = profiles.id
    )
  );

create policy memb_self on memberships
  for select using (user_id = auth.uid() or is_member_of(account_id));

-- ============================================================================
-- 9. Realtime — para que la bandeja se actualice sin recargar
-- ============================================================================

alter publication supabase_realtime add table messages;
alter publication supabase_realtime add table conversations;

commit;
