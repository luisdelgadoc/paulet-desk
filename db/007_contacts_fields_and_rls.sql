-- ============================================================================
-- 007 — Contactos: email/company + cerrar el grant amplio (misma UI real ya)
-- ============================================================================
-- 001_initial_schema.sql dejo contacts con el grant por defecto de Supabase
-- (SELECT/INSERT/UPDATE/DELETE completos para `authenticated`) + una policy
-- "for all" (cont_members) -- a proposito, segun el comentario de 003:
-- "aplicar el mismo tratamiento cuando alguna gane una UI de escritura real
-- desde el navegador, no antes". Esa UI real llega ahora (alta manual de
-- contactos + edicion de email/company desde desk/web/app/(desk)/contacts/) --
-- toca cerrar el grant, mismo patron que 003/004/006 le aplicaron a
-- conversations/messages.
--
-- custom_fields (jsonb, ya existe desde 001) queda FUERA del alcance de
-- escritura del navegador a proposito: es territorio de una fase futura
-- (campos personalizados admin-configurables por cuenta) que todavia no
-- tiene UI -- si se expone antes de tener esa UI, es superficie de escritura
-- sin ningun flujo real detras (el mismo tipo de cosa que 006 cerro).
--
-- phone tambien queda fuera del UPDATE (aunque no del INSERT): cambiar el
-- telefono de un contacto existente rompe el matching por telefono que hace
-- el relay (find_or_create_contact busca por account_id+phone) -- si un
-- cliente real vuelve a escribir despues de que alguien le edito el telefono
-- a mano, el relay crea un contacto DUPLICADO en vez de encontrar el
-- existente. Si hace falta corregir un telefono mal cargado, por ahora se
-- hace desde el SQL Editor, no desde la UI.

begin;

alter table contacts add column if not exists email   text;
alter table contacts add column if not exists company text;

drop policy if exists cont_members on contacts;

create policy cont_select on contacts
  for select using (is_member_of(account_id));

-- El INSERT exige que el account_id que manda el navegador sea uno del que
-- el usuario es miembro (is_member_of via el WITH CHECK) -- no importa que
-- el cliente "se equivoque" de account_id, la fila simplemente se rechaza.
create policy cont_insert on contacts
  for insert with check (is_member_of(account_id));

create policy cont_update on contacts
  for update using (is_member_of(account_id)) with check (is_member_of(account_id));

revoke all on contacts from authenticated;
grant select on contacts to authenticated;
grant insert (account_id, phone, name, email, company) on contacts to authenticated;
grant update (name, email, company) on contacts to authenticated;

commit;
