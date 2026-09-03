-- ============================================================================
-- 003 — Endurecer superficie de escritura del navegador
-- ============================================================================
-- Hallazgo de la revision conjunta Fase 5+6 (revisión posterior): las policies
-- "for all" de 001_initial_schema.sql controlan QUE FILAS se ven, pero el
-- grant de tabla que Supabase deja por defecto para `authenticated` permite
-- las 4 operaciones (SELECT/INSERT/UPDATE/DELETE) sobre esas filas. Hoy es
-- inofensivo porque desk/web/ solo lee -- pero apenas la Fase 7 agregue el
-- boton de takeover, el navegador (con la sola publishable key) podria:
--   - reasignar cualquier conversacion a cualquier usuario (UPDATE assigned_to
--     sin restriccion alguna),
--   - escribir handoff_context_pending arbitrario -- ese texto se antepone
--     al proximo prompt que recibe el agente (Fase 9
--     "Handoff"): es una inyeccion de prompt escribible desde el navegador,
--   - insertar/editar/borrar filas de `messages` con cualquier sender,
--     falseando el registro de lo que dijo el cliente o el bot.
-- Se cierra ahora, antes del boton, porque despues implica tocar la policy Y
-- el codigo del cliente al mismo tiempo, bajo presion de que algo ya se rompio.
--
-- El relay NUNCA se ve afectado por esto: usa la service_role key, que salta
-- RLS y los grants de tabla por diseno (ver docstring de supabase_client.py).
--
-- Alcance de esta migracion: solo `conversations` y `messages`, que son las
-- unicas tablas con exposicion concreta atada a una fase ya planeada (7/9).
-- `accounts`/`profiles`/`channels`/`contacts`/etc. quedan con el grant amplio
-- que ya tenian -- aplicar el mismo tratamiento cuando alguna gane una UI de
-- escritura real desde el navegador, no antes (mismo criterio de "aditivo
-- cuando hace falta" que ya se usa en el resto del esquema).

begin;

-- messages: el navegador SOLO lee. El envio del humano (Fase 8) pasa por
-- POST /outbound del relay (service_role, salta RLS) -- el navegador nunca
-- necesita escribir aqui directamente.
revoke all on messages from authenticated;
grant select on messages to authenticated;

-- conversations: el navegador puede cambiar el estado del gate de takeover
-- (assigned_to, assigned_at, status) -- nada mas. account_id, contact_id,
-- handoff_context_pending y los timestamps quedan fuera de su alcance.
revoke all on conversations from authenticated;
grant select on conversations to authenticated;
grant update (assigned_to, assigned_at, status) on conversations to authenticated;

commit;
