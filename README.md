# Paulet Desk

**Human-in-the-loop inbox for an AI WhatsApp agent.**

A customer messages a business on WhatsApp. An AI agent (built on
[Hermes Agent](https://hermes-agent.nousresearch.com)) answers automatically. Every
message — inbound and outbound — is mirrored to a shared web inbox. A human operator can
take over any conversation with one click: while a conversation is assigned to a person,
the relay stops forwarding to the agent and the human replies directly over WhatsApp.
When the human releases the conversation, the agent resumes — and a plugin injects what
the human said into the agent's next turn, so it doesn't re-ask questions the person
already answered.

This repo is the **shared infrastructure** all client agents connect to. The demo agent,
its persona and knowledge base (`demo-data/`) describe a fictional business
(*Pollos Marios*, a rotisserie-chicken chain); no real business data is included.

---

## How it works

```
 WhatsApp user
      │  (Meta webhook, HMAC-signed)
      ▼
┌─────────────┐   forward (raw body)   ┌──────────────┐
│    relay    │ ─────────────────────▶ │ Hermes Agent │
│  (FastAPI)  │ ◀───────────────────── │  "the agent" │
└──────┬──────┘   agent:end hook       └──────────────┘
       │  mirror every message (in/out)
       ▼
┌─────────────┐        ┌───────────────────────────┐
│  Supabase   │ ◀───── │  web inbox (Next.js 16)    │
│ Postgres +  │        │  conversations · contacts  │
│ Storage +   │ ─────▶ │  pipeline · dashboard      │
│ RLS + Auth  │        └───────────────┬───────────┘
└─────────────┘                        │  "take over" / reply / release
       ▲                               ▼
       └──────────  relay sends human reply via Graph API  ──────────┘
```

**The gate.** `conversations.assigned_to IS NULL` → the agent is live and the relay
forwards to Hermes. Non-null → a human owns the conversation; the relay mirrors the
inbound message but does **not** forward it. Releasing sets it back to `NULL` and stamps
`handoff_context` so the plugin can catch the agent up.

---

## Components

| Path | What it is |
|---|---|
| **`relay/`** | FastAPI service. Validates Meta's `X-Hub-Signature-256` on the **raw** request bytes, forwards to Hermes, mirrors every message to Supabase, sends human replies via the WhatsApp Cloud API (Graph API), downloads inbound media (voice notes, images) to Supabase Storage, and enforces the WhatsApp 24-hour customer-service window. |
| **`web/`** | Next.js 16 (App Router) + React 19 + Tailwind v4. The inbox (conversation list, thread view, media bubbles), plus a lightweight CRM (Contacts, Pipeline, Dashboard). Auth + multi-tenancy via Supabase, enforced with Row-Level Security. |
| **`db/`** | 11 Postgres migrations for Supabase — schema plus progressively tightened RLS. The migration headers document real access-control bugs found and fixed (table `GRANT`s leaking past `FOR ALL` policies, column-level `UPDATE` that had to be revoked, `NOT VALID` uniqueness, etc.). |
| **`hermes-hooks/demo/`** | A Hermes **gateway hook** (`agent:end`): fire-and-forget mirror of the agent's replies to the relay. Resolves its tenant at runtime from the profile's own `.env` — zero hardcoded account IDs, so the folder is copy-paste reusable per client. |
| **`hermes-plugins/demo/`** | A Hermes **plugin** (`pre_llm_call`): injects handoff context into the agent's next turn. Uses the plugin system (whose return value *is* applied) rather than a gateway hook (whose return value is discarded), and never mutates the forwarded webhook body — doing so would invalidate the HMAC that Hermes re-checks. |
| **`demo-data/`** | The agent's `SOUL.md` (persona + conversation rules) and `servicio_al_cliente.md` (knowledge base) for the fictional demo business. |

---

## Stack

FastAPI · Python 3.11 · Next.js 16 · React 19 · Tailwind CSS v4 ·
Supabase (Postgres, Auth, Storage, RLS) · WhatsApp Cloud API / Meta Graph API ·
Hermes Agent (NousResearch) · Caddy · systemd

---

## Design notes

- **Single source of truth for wiring.** The webhook path lives in exactly one file
  (`relay/app/constants.py`); `RELAY_PORT` lives in one `.env` variable that systemd, the
  Caddy scripts, and Python all read from the same place. A value written twice is a
  promise that one day they'll disagree — an earlier version had the port hardcoded in 5
  files and shipped a reversed webhook path to production because of it.
- **HMAC on raw bytes.** Meta signs the exact body it sent; parsing and re-serializing
  changes the bytes and breaks the signature even when the content is "the same".
- **Idempotent ingestion.** Meta retries webhooks that don't get a fast `200`; inbound
  and outbound paths both dedupe.
- **Failures never lose a message.** If media download/upload fails, the row is still
  written — just without a player in the inbox. If the mirror hook fails, the customer
  already has the agent's real reply; the hook swallows the error.
- **Multi-tenant from day one.** `account_id` is resolved from the WhatsApp
  `phone_number_id` via a `channels` table. Onboarding a new client is a row in
  `channels` + a copy of the hook/plugin folders — no code edits.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the phased build and the rationale behind
each decision.

---

## Running it

1. **Supabase**: create a project, run `db/*.sql` in order.
2. **Relay**: `cp relay/.env.example relay/.env` and fill it;
   `pip install -r relay/requirements.txt`; `uvicorn app.main:app --port 8091`.
3. **Web**: `cd web && npm install && cp .env.example .env.local` (fill it) `&& npm run dev`.
4. **WhatsApp**: register the relay's `/whatsapp/webhook` as the Callback URL in
   Meta for Developers; set the same `APP_SECRET` / `VERIFY_TOKEN` in both the relay and
   the Hermes profile.
5. **Agent**: create a Hermes profile from `demo-data/SOUL.md`, drop
   `hermes-hooks/demo/` and `hermes-plugins/demo/` into that profile.

`relay/systemd/`, `web/systemd/`, `Caddyfile` and `*/scripts/deploy*.sh` are included as
a reference deployment (single VPS behind Caddy).
