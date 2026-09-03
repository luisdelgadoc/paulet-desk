import { niceMax, type DailyMessageCounts } from "@/lib/charts";

// SVG a mano, sin libreria de charts -- mismo criterio "sin dependencias
// nuevas" del resto del proyecto. Colores: --series-1/--series-2 (paleta
// categorica validada del skill de dataviz, slots 1-2 -- ver globals.css),
// no elegidos a ojo.
const WIDTH = 640;
const HEIGHT = 220;
const PADDING = { top: 16, right: 16, bottom: 28, left: 34 };

function formatDay(iso: string): string {
  // iso es YYYY-MM-DD (bucketMessagesByDay) -- se ancla a medianoche UTC
  // para que toLocaleDateString no lo corra un dia por el huso horario del
  // navegador.
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("es-CO", { day: "2-digit", month: "2-digit", timeZone: "UTC" });
}

export default function MessagesLineChart({ data }: { data: DailyMessageCounts[] }) {
  const innerW = WIDTH - PADDING.left - PADDING.right;
  const innerH = HEIGHT - PADDING.top - PADDING.bottom;
  const maxRaw = Math.max(0, ...data.map((d) => Math.max(d.inbound, d.outbound)));
  const yMax = niceMax(maxRaw);
  const xStep = data.length > 1 ? innerW / (data.length - 1) : 0;

  const yScale = (v: number) => PADDING.top + innerH - (v / yMax) * innerH;
  const xScale = (i: number) => PADDING.left + i * xStep;

  const pathFor = (key: "inbound" | "outbound") =>
    data.map((d, i) => `${i === 0 ? "M" : "L"}${xScale(i)},${yScale(d[key])}`).join(" ");

  // Con yMax chico (ej. 1, cuando el maximo real de la ventana es 1
  // mensaje) [0, 0.5, 1] redondea a [0, 1, 1] -- 2 gridlines mostrando la
  // misma etiqueta "1". Filtra duplicados por su label redondeado, no por
  // el valor crudo.
  const seenLabels = new Set<string>();
  const yTicks = [0, yMax / 2, yMax].filter((t) => {
    const label = String(Math.round(t));
    if (seenLabels.has(label)) return false;
    seenLabels.add(label);
    return true;
  });
  const labelEvery = Math.max(1, Math.ceil(data.length / 6));

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="img"
        aria-label="Mensajes por día, entrante y saliente"
      >
        {yTicks.map((t) => (
          <g key={t}>
            <line
              x1={PADDING.left}
              x2={WIDTH - PADDING.right}
              y1={yScale(t)}
              y2={yScale(t)}
              stroke="var(--wa-border)"
              strokeWidth={1}
            />
            <text
              x={PADDING.left - 8}
              y={yScale(t)}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize={10}
              fill="var(--wa-text-secondary)"
            >
              {Math.round(t)}
            </text>
          </g>
        ))}

        {data.map((d, i) =>
          i % labelEvery === 0 ? (
            <text
              key={d.date}
              x={xScale(i)}
              y={HEIGHT - PADDING.bottom + 16}
              textAnchor="middle"
              fontSize={10}
              fill="var(--wa-text-secondary)"
            >
              {formatDay(d.date)}
            </text>
          ) : null
        )}

        <path
          d={pathFor("inbound")}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <path
          d={pathFor("outbound")}
          fill="none"
          stroke="var(--series-2)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {data.map((d, i) => (
          <circle
            key={`in-${d.date}`}
            cx={xScale(i)}
            cy={yScale(d.inbound)}
            r={4}
            fill="var(--series-1)"
            stroke="var(--wa-header)"
            strokeWidth={2}
          >
            <title>{`${d.date}: ${d.inbound} entrante${d.inbound === 1 ? "" : "s"}`}</title>
          </circle>
        ))}
        {data.map((d, i) => (
          <circle
            key={`out-${d.date}`}
            cx={xScale(i)}
            cy={yScale(d.outbound)}
            r={4}
            fill="var(--series-2)"
            stroke="var(--wa-header)"
            strokeWidth={2}
          >
            <title>{`${d.date}: ${d.outbound} saliente${d.outbound === 1 ? "" : "s"}`}</title>
          </circle>
        ))}
      </svg>

      {/* Legend -- obligatoria para 2+ series (skill de dataviz), la
          identidad nunca depende solo del color. */}
      <div className="mt-2 flex items-center justify-center gap-4 text-xs text-wa-text-secondary">
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: "var(--series-1)" }}
          />
          Entrante
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: "var(--series-2)" }}
          />
          Saliente
        </span>
      </div>
    </div>
  );
}
