// Helpers puros para los graficos SVG hechos a mano del Dashboard (sin
// libreria de charts -- mismo criterio de "sin dependencias nuevas" que el
// resto del proyecto). Mismo patron que messagePreview.ts/avatar.ts/phone.ts:
// logica de calculo separada del render.

// Hallazgo real de la una revisión de código posterior (2026-08-10): calcular "hoy" en UTC
// crudo hace que los contadores del Dashboard ("Contactos nuevos hoy",
// "Mensajes enviados hoy") se reinicien a las 7pm hora Peru/Colombia (UTC-5)
// -- justo la franja de mas actividad para un negocio como Demo. Peru y
// Colombia son UTC-5 fijo, sin horario de verano, asi que un offset
// hardcodeado alcanza -- si Paulet Desk sirve algun dia una cuenta en otro
// huso horario, esto necesita moverse a una columna de configuracion por
// cuenta, no antes.
export const BUSINESS_TZ_OFFSET_MS = -5 * 60 * 60 * 1000;

// "Desplaza" un instante real a un Date cuyos getters UTC devuelven el
// calendario/hora LOCAL del negocio -- truco estandar para hacer aritmetica
// de fecha sin depender de la zona horaria del navegador (el servidor y el
// cliente pueden estar en cualquier huso, esto no depende de ninguno de los
// dos).
function shiftToBusinessTZ(ms: number): Date {
  return new Date(ms + BUSINESS_TZ_OFFSET_MS);
}

// Inverso de shiftToBusinessTZ: dado un instante ya "desplazado" (tratado
// como si sus getters UTC fueran hora local), devuelve el instante REAL
// (UTC de verdad) que le corresponde.
function unshiftFromBusinessTZ(shiftedMs: number): Date {
  return new Date(shiftedMs - BUSINESS_TZ_OFFSET_MS);
}

// Instante UTC real de la medianoche de HOY en la zona horaria del negocio.
export function startOfTodayInBusinessTZ(): string {
  const shifted = shiftToBusinessTZ(Date.now());
  const startShifted = Date.UTC(
    shifted.getUTCFullYear(),
    shifted.getUTCMonth(),
    shifted.getUTCDate()
  );
  return unshiftFromBusinessTZ(startShifted).toISOString();
}

// Instante UTC real de la medianoche de hace `days` dias, misma zona.
export function daysAgoStartInBusinessTZ(days: number): string {
  const shifted = shiftToBusinessTZ(Date.now());
  const startShifted = Date.UTC(
    shifted.getUTCFullYear(),
    shifted.getUTCMonth(),
    shifted.getUTCDate() - days
  );
  return unshiftFromBusinessTZ(startShifted).toISOString();
}

// Clave YYYY-MM-DD del dia calendario de negocio al que pertenece un
// timestamp -- para bucketMessagesByDay.
function businessDateKey(iso: string): string {
  const shifted = shiftToBusinessTZ(new Date(iso).getTime());
  return shifted.toISOString().slice(0, 10);
}

// Redondea el maximo del eje Y a un numero "limpio" (1/2/5 x 10^n) -- mismo
// criterio que pide el skill de dataviz para los ticks del eje ("round to
// clean numbers (0 / 1,000 / 2,000)"). Sin esto, un maximo real de 743
// produce un eje con ticks en 743/371.5/0, ilegible.
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const normalized = value / magnitude;
  let niceNormalized: number;
  if (normalized <= 1) niceNormalized = 1;
  else if (normalized <= 2) niceNormalized = 2;
  else if (normalized <= 5) niceNormalized = 5;
  else niceNormalized = 10;
  return niceNormalized * magnitude;
}

export interface DailyMessageCounts {
  date: string; // YYYY-MM-DD
  inbound: number;
  outbound: number;
}

// Arma `days` cubetas diarias consecutivas terminando HOY, en cero, y suma
// los mensajes que caen en cada una. Bucketing por dia CALENDARIO DEL NEGOCIO
// (BUSINESS_TZ_OFFSET_MS), no UTC crudo -- corregido tras la revision de
// una revisión posterior: bucketear por el prefijo YYYY-MM-DD de created_at (UTC) corria
// varias horas desfasado del dia real en Peru/Colombia, e inconsistente con
// el "hoy" ya corregido de startOfTodayInBusinessTZ.
export function bucketMessagesByDay(
  messages: { direction: "inbound" | "outbound"; created_at: string }[],
  days: number
): DailyMessageCounts[] {
  const buckets: DailyMessageCounts[] = [];
  const byDate = new Map<string, DailyMessageCounts>();
  const todayShifted = shiftToBusinessTZ(Date.now());

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(todayShifted);
    d.setUTCDate(d.getUTCDate() - i);
    const key = d.toISOString().slice(0, 10);
    const bucket: DailyMessageCounts = { date: key, inbound: 0, outbound: 0 };
    byDate.set(key, bucket);
    buckets.push(bucket);
  }

  for (const m of messages) {
    const key = businessDateKey(m.created_at);
    const bucket = byDate.get(key);
    if (!bucket) continue; // fuera de la ventana pedida
    if (m.direction === "inbound") bucket.inbound += 1;
    else bucket.outbound += 1;
  }

  return buckets;
}

// Spec del skill de dataviz (marks-and-anatomy.md): "4px rounded data-end,
// square at the baseline -- grows from a single baseline". Un <rect rx> liso
// redondea las 4 esquinas; esto arma el path a mano para redondear SOLO las
// 2 esquinas superiores.
export function topRoundedRectPath(
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number
): string {
  if (height <= 0 || width <= 0) return "";
  const r = Math.min(radius, width / 2, height);
  return (
    `M${x},${y + height} ` +
    `L${x},${y + r} ` +
    `Q${x},${y} ${x + r},${y} ` +
    `L${x + width - r},${y} ` +
    `Q${x + width},${y} ${x + width},${y + r} ` +
    `L${x + width},${y + height} Z`
  );
}
