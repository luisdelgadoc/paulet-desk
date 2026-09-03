"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import {
  bucketMessagesByDay,
  startOfTodayInBusinessTZ,
  daysAgoStartInBusinessTZ,
  type DailyMessageCounts,
} from "@/lib/charts";
import { averageFirstResponseMinutes } from "@/lib/responseTime";
import type { DealStage } from "@/lib/types";
import MessagesLineChart from "@/components/MessagesLineChart";
import StageBarChart from "@/components/StageBarChart";

// Reutiliza datos que ya existen (messages, contacts, deal_stages, deals) --
// SIN tablas propias, SIN migración para esta fase (confirmado: authenticated
// ya tiene SELECT en las 4 desde 004/007/009). Refresh al cargar + botón
// manual, sin Realtime -- mismo criterio ya usado en Contactos y Pipeline
// (ver ARCHITECTURE.md, "Plan acordado").
//
// Ajustado tras la una revisión de código posterior (2026-08-10) -- ver ARCHITECTURE.md, "Revisión
// Pipeline+Dashboard" para el detalle completo de cada hallazgo.
const DAYS_WINDOW = 14;

// "Activas" redefinido por RECENCIA, no por `status` -- hallazgo real:
// ningun flujo del proyecto escribe status='closed' todavia (no existe
// funcion de cerrar una conversacion), asi que filtrar por status='open'
// contaba TODAS las conversaciones que existieron alguna vez, no las
// activas de verdad. Una conversacion con actividad en los ultimos 7 dias
// es una definicion honesta de "activa" que no depende de una feature que
// no existe -- el label lo dice explicito para que no se lea como "abiertas
// ahora mismo".
const ACTIVE_CONVERSATION_WINDOW_DAYS = 7;

// Techo de filas para las 2 consultas que antes no tenian ninguno --
// generoso para el volumen real de esta demo, pero real: sin esto una
// cuenta con miles de deals o mensajes en la ventana de 14 dias no tenia
// ningun limite.
const DEALS_QUERY_LIMIT = 2000;
const MESSAGES_QUERY_LIMIT = 5000;

// El calculo de primera respuesta ya no embebe el historial completo de 100
// conversaciones (podia ser un payload enorme) -- ahora consulta `messages`
// directo, acotado por ventana de tiempo + un limite de filas, y agrupa por
// conversation_id en la funcion pura (ver lib/responseTime.ts). Tradeoff
// consciente: una conversacion cuyo PRIMER mensaje real quedo fuera de la
// ventana puede no medirse bien (falta su punto de partida real) -- aceptable
// para una metrica de "como estamos respondiendo ULTIMAMENTE", no un audit
// historico exacto.
const RESPONSE_TIME_WINDOW_DAYS = 30;
const RESPONSE_TIME_MESSAGE_LIMIT = 3000;

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

function formatResponseTime(min: number): string {
  if (min < 60) return `${Math.round(min)} min`;
  const hours = Math.floor(min / 60);
  const mins = Math.round(min % 60);
  return `${hours}h ${mins}min`;
}

interface Metrics {
  activeConversations: number;
  newContactsToday: number;
  outboundToday: number;
  pipelineValue: number;
  lostValue: number;
  stageValues: { name: string; value: number; isLost: boolean }[];
  dailyCounts: DailyMessageCounts[];
  avgResponseMinutes: number | null;
}

export default function DashboardPage() {
  const { loading: loadingSession } = useRequireSession();
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;

    async function load() {
      const [
        activeConvRes,
        newContactsRes,
        outboundTodayRes,
        stagesRes,
        dealsRes,
        recentMessagesRes,
        responseMessagesRes,
      ] = await Promise.all([
        supabase
          .from("conversations")
          .select("id", { count: "exact", head: true })
          .gte("last_message_at", daysAgoStartInBusinessTZ(ACTIVE_CONVERSATION_WINDOW_DAYS)),
        supabase
          .from("contacts")
          .select("id", { count: "exact", head: true })
          .gte("created_at", startOfTodayInBusinessTZ()),
        supabase
          .from("messages")
          .select("id", { count: "exact", head: true })
          .eq("direction", "outbound")
          .gte("created_at", startOfTodayInBusinessTZ()),
        supabase.from("deal_stages").select("*").order("position", { ascending: true }),
        supabase
          .from("deals")
          .select("stage_id, value_cop")
          .order("created_at", { ascending: false })
          .limit(DEALS_QUERY_LIMIT),
        supabase
          .from("messages")
          .select("direction, created_at")
          .gte("created_at", daysAgoStartInBusinessTZ(DAYS_WINDOW - 1))
          .order("created_at", { ascending: true })
          .limit(MESSAGES_QUERY_LIMIT),
        supabase
          .from("messages")
          .select("conversation_id, direction, created_at")
          .gte("created_at", daysAgoStartInBusinessTZ(RESPONSE_TIME_WINDOW_DAYS))
          .order("created_at", { ascending: true })
          .limit(RESPONSE_TIME_MESSAGE_LIMIT),
      ]);

      if (!active) return;

      const errors = [
        activeConvRes.error,
        newContactsRes.error,
        outboundTodayRes.error,
        stagesRes.error,
        dealsRes.error,
        recentMessagesRes.error,
        responseMessagesRes.error,
      ].filter((e) => e != null);

      if (errors.length > 0) {
        console.error(
          "Error cargando dashboard:",
          errors.map((e) => e?.message).join(" | ")
        );
        setLoadError("No se pudo cargar el dashboard.");
        setLoading(false);
        return;
      }

      const stages = (stagesRes.data ?? []) as DealStage[];
      const deals = (dealsRes.data ?? []) as {
        stage_id: string;
        value_cop: number | null;
      }[];
      const lostStageIds = new Set(
        stages.filter((s) => s.is_lost_stage).map((s) => s.id)
      );

      // Excluye la etapa de perdida del valor "activo" -- un deal
      // rechazado no debe seguir sumando al pipeline solo porque nadie lo
      // borró. Se muestra aparte, no se descarta.
      const pipelineValue = deals
        .filter((d) => !lostStageIds.has(d.stage_id))
        .reduce((sum, d) => sum + (d.value_cop ?? 0), 0);
      const lostValue = deals
        .filter((d) => lostStageIds.has(d.stage_id))
        .reduce((sum, d) => sum + (d.value_cop ?? 0), 0);

      const stageValues = stages.map((s) => ({
        name: s.name,
        isLost: s.is_lost_stage,
        value: deals
          .filter((d) => d.stage_id === s.id)
          .reduce((sum, d) => sum + (d.value_cop ?? 0), 0),
      }));

      const dailyCounts = bucketMessagesByDay(
        (recentMessagesRes.data ?? []) as {
          direction: "inbound" | "outbound";
          created_at: string;
        }[],
        DAYS_WINDOW
      );

      const avgResponseMinutes = averageFirstResponseMinutes(
        (responseMessagesRes.data ?? []) as {
          conversation_id: string;
          direction: "inbound" | "outbound";
          created_at: string;
        }[]
      );

      setLoadError(null);
      setMetrics({
        activeConversations: activeConvRes.count ?? 0,
        newContactsToday: newContactsRes.count ?? 0,
        outboundToday: outboundTodayRes.count ?? 0,
        pipelineValue,
        lostValue,
        stageValues,
        dailyCounts,
        avgResponseMinutes,
      });
      setLoading(false);
    }

    load();

    return () => {
      active = false;
    };
  }, [refreshKey]);

  function refresh() {
    setLoading(true);
    setRefreshKey((k) => k + 1);
  }

  if (loadingSession) {
    return null;
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-wa-list-bg">
      <header className="flex items-center justify-between border-b border-wa-border bg-wa-header px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Dashboard</h1>
          <p className="text-sm text-wa-text-secondary">
            Métricas de conversaciones, contactos y pipeline.
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          title="Refrescar"
          className="rounded border border-wa-border px-3 py-2 text-sm text-wa-text-secondary hover:bg-wa-hover disabled:opacity-50"
        >
          ↻
        </button>
      </header>

      <div className="flex-1 px-6 py-4">
        {loading ? (
          <p className="text-sm text-wa-text-secondary">Cargando dashboard...</p>
        ) : loadError ? (
          <div>
            <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
            <button
              onClick={refresh}
              className="mt-2 text-sm text-wa-accent hover:underline"
            >
              Reintentar
            </button>
          </div>
        ) : metrics ? (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
              <StatTile
                label={`Conversaciones activas (${ACTIVE_CONVERSATION_WINDOW_DAYS}d)`}
                value={String(metrics.activeConversations)}
              />
              <StatTile label="Contactos nuevos hoy" value={String(metrics.newContactsToday)} />
              <StatTile label="Mensajes enviados hoy" value={String(metrics.outboundToday)} />
              <StatTile label="Valor de pipeline" value={cop.format(metrics.pipelineValue)} />
              <StatTile label="Valor perdido" value={cop.format(metrics.lostValue)} danger />
              <StatTile
                label="1ra respuesta (prom.)"
                value={
                  metrics.avgResponseMinutes != null
                    ? formatResponseTime(metrics.avgResponseMinutes)
                    : "—"
                }
              />
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-wa-border bg-wa-header p-4">
                <h2 className="mb-2 text-sm font-semibold text-foreground">
                  Mensajes por día ({DAYS_WINDOW} días)
                </h2>
                <MessagesLineChart data={metrics.dailyCounts} />
              </div>
              <div className="rounded-lg border border-wa-border bg-wa-header p-4">
                <h2 className="mb-2 text-sm font-semibold text-foreground">
                  Pipeline por etapa
                </h2>
                <StageBarChart stages={metrics.stageValues} />
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

function StatTile({
  label,
  value,
  danger,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className="rounded-lg border border-wa-border bg-wa-header p-3">
      <p className="text-xs text-wa-text-secondary">{label}</p>
      <p
        className={`mt-1 text-xl font-semibold ${
          danger ? "text-red-600 dark:text-red-400" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
