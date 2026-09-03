# Architecture notes

Design rationale behind Paulet Desk. Referenced from code comments as "las notas de
arquitectura".

## Why a relay at all

Hermes Agent already connects natively to WhatsApp — so why put a FastAPI service in
front? Because the product needs a **human** to be able to step into any conversation,
and Hermes has no concept of "this conversation is currently owned by a person, don't
answer it". The relay owns that state. Meta's webhook points at the relay; the relay
decides, per message, whether to forward to Hermes.

## The gate (human-in-the-loop)

`conversations.assigned_to`:

- `NULL` → the agent is live. The relay forwards the inbound webhook to Hermes and
  mirrors both sides to `messages`.
- non-null → a human owns it. The relay still mirrors the inbound message (so the
  operator sees it) but does **not** forward to Hermes. Human replies go out through the
  relay via the Graph API.

"Release" sets `assigned_to` back to `NULL` and writes `handoff_context` — a short
summary of what the human said while they had it.

## Hook vs. plugin — two different Hermes extension points

Hermes has two separate systems, and the difference matters here:

| | Gateway hooks (`~/.hermes/hooks/`) | Plugins (`~/.hermes/plugins/`) |
|---|---|---|
| Events | `agent:start`, `agent:end`, … | `pre_llm_call`, … |
| Return value | **discarded** (fire-and-forget) | **applied** to the turn |
| Used here for | mirroring the agent's reply out to the relay | injecting handoff context into the next turn |

- **`hermes-hooks/demo/mirror-to-relay/`** rides `agent:end`. It can't block or veto the
  turn (return value is discarded by design), which is exactly right: a failure here
  (relay down, Supabase down) must never delay the reply the customer already received.
  Short timeout, errors swallowed.
- **`hermes-plugins/demo/inject-handoff-context/`** rides `pre_llm_call`, whose return
  value *is* merged into the user message for that turn. It reads `handoff_context` from
  Supabase and injects it so the agent doesn't re-ask what the human already resolved.
  It is **synchronous** (the plugin manager calls `cb(**kwargs)` with no `await` — an
  `async def` would never run), and fails silent (return `None` → turn proceeds
  unchanged, same as before this feature existed).

### Why the plugin doesn't just edit the forwarded webhook

The relay forwards the **raw** webhook body to Hermes, and Hermes re-validates the HMAC
over those exact bytes. Injecting text into the body would invalidate the signature. The
plugin acts one step later — after Hermes has already accepted the turn and is about to
call the LLM.

## Row-Level Security, tightened in stages

The `db/` migrations show RLS being hardened as real holes were found:

- `FOR ALL` policies control *which rows* are visible, but the table `GRANT` Supabase
  leaves for `authenticated` by default still allowed operations the policies were meant
  to prevent — fixed by revoking the grants explicitly (`003`, `004`).
- Column-level `UPDATE` on `conversations.status` / `contacts` fields had to be revoked
  so clients couldn't move state the server owns (`006`, `008`).
- `conversations` needs "at most one open conversation per contact" — enforced with a
  partial unique index, added `NOT VALID` then validated to avoid locking a live table
  (`002`).

## Multi-tenancy

`account_id` is never hardcoded. It's resolved from the inbound message's
`phone_number_id` against a `channels` table (`relay/app/supabase_client.get_account_id_for_phone_number`).
The Hermes hook and plugin folders resolve their own tenant the same way — from the
profile's `.env`, located by path position, not by a client name. Onboarding a client is:
a row in `channels`, a Hermes profile, and a copy of the hook/plugin folders. No code
changes.

## Media

Inbound audio/image/video/document/sticker is downloaded from the Graph API and uploaded
to a private Supabase Storage bucket **before** the `messages` row is inserted, so
`media_url` is populated from the first write. A failure in that path never drops the
message — the row is written without a player.

## The 24-hour window

WhatsApp only allows free-form business-initiated messages within 24h of the customer's
last message. `relay/app/window_24h.py` checks this before a human's outbound reply;
outside the window the operator gets a clear error instead of a silent Graph API
rejection. (Approved message templates for outside-window replies are future work.)

## Single source of truth

`relay/app/constants.py` holds the webhook path — nothing else re-types the string
`"/whatsapp/webhook"`. `RELAY_PORT` lives once in `.env`; systemd, the Caddy switch
scripts, and Python all read it from there. This rule exists because an earlier version
hardcoded the port in five files and the webhook path in four, and shipped a reversed
path to production because no one checked the assumed value against the one registered in
Meta's dashboard.
