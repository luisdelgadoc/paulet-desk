-- ============================================================================
-- 005 — Storage para media entrante de WhatsApp (Fase 10)
-- ============================================================================
-- Bucket privado (no publico): las notas de voz/imagenes de un cliente no
-- deben quedar accesibles por URL adivinable en internet. El relay sube con
-- la service_role key (salta RLS de Storage igual que salta RLS de tablas).
-- El navegador pide una signed URL bajo demanda (supabase.storage.from(...)
-- .createSignedUrl(...)), que Supabase solo entrega si la policy SELECT de
-- abajo lo permite -- mismo patron is_member_of() que ya protege las tablas,
-- aplicado ahora a storage.objects.
--
-- Convencion de path: {account_id}/{wamid}.{ext} -- el primer segmento del
-- path (storage.foldername(name)[1]) es el account_id, que la policy usa
-- para restringir la lectura a miembros de esa cuenta exactamente igual que
-- is_member_of(account_id) en las tablas normales.

begin;

insert into storage.buckets (id, name, public)
values ('whatsapp-media', 'whatsapp-media', false)
on conflict (id) do nothing;

create policy "demo members can read whatsapp media"
on storage.objects for select
to authenticated
using (
  bucket_id = 'whatsapp-media'
  and is_member_of((storage.foldername(name))[1]::uuid)
);

commit;
