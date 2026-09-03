"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
  type SyntheticEvent,
} from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { latestConversationByContact } from "@/lib/conversationLookup";
import type { DealStage, DealWithContact } from "@/lib/types";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

// v1 a proposito acotado (ver ARCHITECTURE.md, "Fase Contactos" -- mismo criterio
// de no abrir superficie sin flujo real detras): sin gestion de etapas
// (agregar/renombrar/reordenar se hace por SQL Editor por ahora, RLS de
// deal_stages es solo lectura -- ver 009_deals_pipeline.sql), sin boton
// "Agregar deal" manual -- los deals se crean solos via el trigger
// on_contact_created_seed_deal cuando llega un contacto nuevo (por WhatsApp
// o alta manual, cualquiera de los dos caminos). notes sigue sin editarse.
//
// value_cop SI se edita desde acá (agregado en la una revisión de código posterior,
// 2026-08-10 -- ver 011_deals_lost_stage_and_value.sql para el grant nuevo):
// decision explicita del usuario de que el Dashboard necesita un valor real,
// no ceros permanentes -- se carga tipicamente cuando el deal llega a
// "Cotizado", pero el campo queda editable en CUALQUIER etapa (permite
// corregir o renegociar despues, no solo cargar una vez).
export default function PipelinePage() {
  const router = useRouter();
  const { loading: loadingSession } = useRequireSession();

  const [stages, setStages] = useState<DealStage[]>([]);
  const [deals, setDeals] = useState<DealWithContact[]>([]);
  // contact_id -> id de su conversacion mas reciente, para poder navegar al
  // hacer click en una tarjeta. Logica de agrupamiento compartida con
  // Contactos via lib/conversationLookup.ts -- la CONSULTA sigue siendo
  // distinta a proposito (ver el comentario en ese archivo).
  const [conversationByContact, setConversationByContact] = useState<
    Map<string, string>
  >(new Map());

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [moveError, setMoveError] = useState<string | null>(null);

  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverStage, setDragOverStage] = useState<string | null>(null);

  // Edicion inline del valor cotizado. savingValueRef es un latch sincronico
  // -- mismo motivo que savingRef en Contactos: evita doble submit si el
  // usuario aprieta Enter dos veces antes de que React vuelva a renderizar.
  const [editingDealId, setEditingDealId] = useState<string | null>(null);
  const [editingValueInput, setEditingValueInput] = useState("");
  const [editingValueError, setEditingValueError] = useState<string | null>(null);
  const savingValueRef = useRef(false);

  useEffect(() => {
    let active = true;

    async function load() {
      const [stagesRes, dealsRes] = await Promise.all([
        supabase.from("deal_stages").select("*").order("position", { ascending: true }),
        supabase
          .from("deals")
          .select("*, contacts(id, name, phone)")
          .order("created_at", { ascending: true }),
      ]);

      if (!active) return;

      if (stagesRes.error || dealsRes.error) {
        console.error(
          "Error cargando pipeline:",
          stagesRes.error?.message,
          dealsRes.error?.message
        );
        setLoadError("No se pudo cargar el pipeline.");
        setLoading(false);
        return;
      }

      setLoadError(null);
      setStages((stagesRes.data ?? []) as DealStage[]);
      const dealsTyped = (dealsRes.data ?? []) as DealWithContact[];
      setDeals(dealsTyped);

      const contactIds = [...new Set(dealsTyped.map((d) => d.contact_id))];
      if (contactIds.length > 0) {
        const { data: convs, error: convError } = await supabase
          .from("conversations")
          .select("id, contact_id, created_at")
          .in("contact_id", contactIds);
        if (active && !convError) {
          setConversationByContact(latestConversationByContact(convs ?? []));
        }
      }

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

  const dealsByStage = useMemo(() => {
    const map = new Map<string, DealWithContact[]>();
    for (const stage of stages) map.set(stage.id, []);
    for (const deal of deals) {
      const list = map.get(deal.stage_id);
      if (list) list.push(deal);
    }
    return map;
  }, [stages, deals]);

  // Excluye la etapa marcada is_lost_stage -- mismo criterio que el
  // Dashboard (una revisión de código posterior, 2026-08-10): un deal rechazado no debe
  // seguir contando como "pipeline abierto" solo porque nadie lo borró.
  // Sin este ajuste, esta pantalla y el Dashboard mostrarían 2 números
  // distintos para lo que se supone es la misma métrica.
  const lostStageIds = useMemo(
    () => new Set(stages.filter((s) => s.is_lost_stage).map((s) => s.id)),
    [stages]
  );
  const pipelineValue = deals
    .filter((d) => !lostStageIds.has(d.stage_id))
    .reduce((sum, d) => sum + (d.value_cop ?? 0), 0);

  function openDeal(deal: DealWithContact) {
    const conversationId = conversationByContact.get(deal.contact_id);
    if (conversationId) router.push(`/conversations/${conversationId}`);
  }

  // Optimista: la tarjeta se mueve en pantalla de inmediato, se revierte si
  // el UPDATE falla -- sin esto, arrastrar se siente con lag esperando el
  // round-trip a Supabase antes de que la tarjeta "aterrice".
  async function moveDeal(dealId: string, newStageId: string) {
    const deal = deals.find((d) => d.id === dealId);
    if (!deal || deal.stage_id === newStageId) return;
    const previousStageId = deal.stage_id;

    setMoveError(null);
    setDeals((current) =>
      current.map((d) => (d.id === dealId ? { ...d, stage_id: newStageId } : d))
    );

    const { error } = await supabase
      .from("deals")
      .update({ stage_id: newStageId })
      .eq("id", dealId);

    if (error) {
      console.error("Error moviendo deal:", error.message);
      setMoveError("No se pudo mover la tarjeta -- se revirtió.");
      setDeals((current) =>
        current.map((d) => (d.id === dealId ? { ...d, stage_id: previousStageId } : d))
      );
    }
  }

  function startEditValue(e: ReactMouseEvent, deal: DealWithContact) {
    e.stopPropagation(); // no disparar openDeal ni el drag
    setEditingDealId(deal.id);
    setEditingValueInput(deal.value_cop != null ? String(deal.value_cop) : "");
    setEditingValueError(null);
  }

  function cancelEditValue(e?: SyntheticEvent) {
    e?.stopPropagation();
    setEditingDealId(null);
    setEditingValueError(null);
  }

  async function saveEditValue(e: FormEvent, dealId: string) {
    e.preventDefault();
    e.stopPropagation();
    if (savingValueRef.current) return;

    const trimmed = editingValueInput.trim();
    // Vacio = borrar el valor (vuelve a null), no un error.
    let parsed: number | null = null;
    if (trimmed !== "") {
      parsed = Number(trimmed);
      if (!Number.isFinite(parsed) || parsed < 0) {
        setEditingValueError("Ingresa un número válido (sin puntos ni comas).");
        return;
      }
    }

    savingValueRef.current = true;
    const previous = deals.find((d) => d.id === dealId)?.value_cop ?? null;

    // Optimista, mismo patron que moveDeal.
    setDeals((current) =>
      current.map((d) => (d.id === dealId ? { ...d, value_cop: parsed } : d))
    );
    setEditingDealId(null);

    const { error } = await supabase
      .from("deals")
      .update({ value_cop: parsed })
      .eq("id", dealId);

    savingValueRef.current = false;

    if (error) {
      console.error("Error guardando el valor:", error.message);
      setMoveError("No se pudo guardar el valor -- se revirtió.");
      setDeals((current) =>
        current.map((d) => (d.id === dealId ? { ...d, value_cop: previous } : d))
      );
    }
  }

  function handleDragStart(e: DragEvent<HTMLDivElement>, dealId: string) {
    e.dataTransfer.setData("text/plain", dealId);
    e.dataTransfer.effectAllowed = "move";
    setDraggingId(dealId);
  }

  function handleDragEnd() {
    setDraggingId(null);
    setDragOverStage(null);
  }

  function handleDragOverColumn(e: DragEvent<HTMLDivElement>, stageId: string) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverStage !== stageId) setDragOverStage(stageId);
  }

  function handleDropColumn(e: DragEvent<HTMLDivElement>, stageId: string) {
    e.preventDefault();
    const dealId = e.dataTransfer.getData("text/plain");
    setDragOverStage(null);
    setDraggingId(null);
    if (dealId) moveDeal(dealId, stageId);
  }

  if (loadingSession) {
    return null;
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-wa-list-bg">
      <header className="flex items-center justify-between border-b border-wa-border bg-wa-header px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Pipeline</h1>
          <p className="text-sm text-wa-text-secondary">
            {deals.length} deal{deals.length === 1 ? "" : "s"} · {cop.format(pipelineValue)}
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

      {moveError && (
        <p className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          {moveError}
        </p>
      )}

      <div className="flex-1 overflow-x-auto overflow-y-hidden px-6 py-4">
        {loading ? (
          <p className="text-sm text-wa-text-secondary">Cargando pipeline...</p>
        ) : loadError ? (
          <div>
            <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
            <button onClick={refresh} className="mt-2 text-sm text-wa-accent hover:underline">
              Reintentar
            </button>
          </div>
        ) : stages.length === 0 ? (
          <p className="text-sm text-wa-text-secondary">
            Esta cuenta todavía no tiene etapas configuradas.
          </p>
        ) : (
          <div className="flex h-full gap-3">
            {stages.map((stage) => {
              const stageDeals = dealsByStage.get(stage.id) ?? [];
              const stageValue = stageDeals.reduce(
                (sum, d) => sum + (d.value_cop ?? 0),
                0
              );
              const isDragOver = dragOverStage === stage.id;
              return (
                <div
                  key={stage.id}
                  onDragOver={(e) => handleDragOverColumn(e, stage.id)}
                  onDrop={(e) => handleDropColumn(e, stage.id)}
                  className={`flex w-40 shrink-0 flex-col overflow-hidden rounded-lg border bg-wa-header ${
                    isDragOver ? "border-wa-accent" : "border-wa-border"
                  }`}
                >
                  <div
                    className="h-1 shrink-0"
                    style={{ backgroundColor: stage.color }}
                  />
                  <div className="border-b border-wa-border px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">
                        {stage.name}
                      </span>
                      <span className="shrink-0 text-xs text-wa-text-secondary">
                        {stageDeals.length}
                      </span>
                    </div>
                    <p className="text-xs text-wa-text-secondary">{cop.format(stageValue)}</p>
                  </div>
                  <div className="flex-1 min-h-[160px] space-y-2 overflow-y-auto p-2">
                    {stageDeals.length === 0 ? (
                      <p className="rounded border border-dashed border-wa-border p-3 text-center text-xs text-wa-text-secondary">
                        Sin deals
                      </p>
                    ) : (
                      stageDeals.map((deal) => {
                        const hasConversation = conversationByContact.has(deal.contact_id);
                        const isEditingValue = editingDealId === deal.id;
                        return (
                          <div
                            key={deal.id}
                            draggable={!isEditingValue}
                            onDragStart={(e) => handleDragStart(e, deal.id)}
                            onDragEnd={handleDragEnd}
                            onClick={() => !isEditingValue && openDeal(deal)}
                            title={
                              hasConversation
                                ? "Arrastra para cambiar de etapa, click para abrir la conversación"
                                : "Arrastra para cambiar de etapa -- sin conversación por WhatsApp todavía"
                            }
                            className={`rounded border border-wa-border bg-wa-list-bg p-2.5 text-sm active:cursor-grabbing ${
                              hasConversation ? "cursor-pointer" : "cursor-grab"
                            } ${draggingId === deal.id ? "opacity-40" : ""}`}
                          >
                            <p className="truncate font-medium text-foreground">
                              {deal.contacts?.name || deal.contacts?.phone || "Contacto"}
                            </p>
                            <p className="truncate text-xs text-wa-text-secondary">
                              {deal.contacts?.phone}
                            </p>

                            {isEditingValue ? (
                              <form
                                onSubmit={(e) => saveEditValue(e, deal.id)}
                                onClick={(e) => e.stopPropagation()}
                                className="mt-1 flex items-center gap-1"
                              >
                                <input
                                  autoFocus
                                  type="text"
                                  inputMode="numeric"
                                  value={editingValueInput}
                                  onChange={(e) => setEditingValueInput(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Escape") cancelEditValue(e);
                                  }}
                                  placeholder="COP"
                                  className="w-full min-w-0 rounded border border-wa-border bg-background px-1.5 py-0.5 text-xs text-foreground"
                                />
                                <button
                                  type="submit"
                                  title="Guardar"
                                  className="shrink-0 text-xs text-wa-accent"
                                >
                                  ✓
                                </button>
                                <button
                                  type="button"
                                  onClick={cancelEditValue}
                                  title="Cancelar"
                                  className="shrink-0 text-xs text-wa-text-secondary"
                                >
                                  ✕
                                </button>
                              </form>
                            ) : (
                              <button
                                type="button"
                                onClick={(e) => startEditValue(e, deal)}
                                title="Editar valor cotizado"
                                className="mt-1 block text-xs font-medium text-wa-accent hover:underline"
                              >
                                {deal.value_cop != null
                                  ? cop.format(deal.value_cop)
                                  : "+ Agregar valor"}
                              </button>
                            )}
                            {isEditingValue && editingValueError && (
                              <p className="mt-0.5 text-[10px] text-red-600 dark:text-red-400">
                                {editingValueError}
                              </p>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
