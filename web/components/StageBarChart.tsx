import { niceMax, topRoundedRectPath } from "@/lib/charts";

// Comparacion de MAGNITUD (cuanto vale cada etapa), no de identidad -- cada
// barra ya lleva el nombre de la etapa como etiqueta en el eje, asi que la
// identidad no depende del color. Por eso un solo hue (--wa-accent, el
// acento de marca del proyecto), no una paleta categorica de 6 colores --
// el propio skill de dataviz distingue "compare magnitude" (secuencial, un
// hue) de "tell distinct series apart" (categorico), y esto es lo primero.
//
// Excepcion deliberada: la barra de la etapa marcada isLost (Perdido) usa
// --status-danger en vez de --wa-accent -- no es una categoria mas, es un
// ESTADO (dinero que se perdio, no que esta en progreso). El skill reserva
// los colores de status para esto exactamente: "never reused for series N".
const WIDTH = 640;
const HEIGHT = 200;
const PADDING = { top: 20, right: 12, bottom: 40, left: 12 };
const MAX_LABEL_CHARS = 11;

const copCompact = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
  notation: "compact",
});
const copFull = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

export default function StageBarChart({
  stages,
}: {
  stages: { name: string; value: number; isLost: boolean }[];
}) {
  const innerW = WIDTH - PADDING.left - PADDING.right;
  const innerH = HEIGHT - PADDING.top - PADDING.bottom;
  const maxRaw = Math.max(0, ...stages.map((s) => s.value));
  const yMax = niceMax(maxRaw);
  const groupWidth = stages.length > 0 ? innerW / stages.length : innerW;
  const barWidth = Math.min(28, groupWidth * 0.6);

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="h-auto w-full"
      role="img"
      aria-label="Valor de pipeline por etapa, en pesos colombianos"
    >
      <line
        x1={PADDING.left}
        x2={WIDTH - PADDING.right}
        y1={PADDING.top + innerH}
        y2={PADDING.top + innerH}
        stroke="var(--wa-border)"
        strokeWidth={1}
      />
      {stages.map((s, i) => {
        const barH = yMax > 0 ? (s.value / yMax) * innerH : 0;
        const cx = PADDING.left + i * groupWidth + groupWidth / 2;
        const x = cx - barWidth / 2;
        const y = PADDING.top + innerH - barH;
        const label =
          s.name.length > MAX_LABEL_CHARS
            ? `${s.name.slice(0, MAX_LABEL_CHARS - 1)}…`
            : s.name;
        return (
          <g key={s.name}>
            <path
              d={topRoundedRectPath(x, y, barWidth, barH, 4)}
              fill={s.isLost ? "var(--status-danger)" : "var(--wa-accent)"}
            >
              <title>{`${s.name}: ${copFull.format(s.value)}`}</title>
            </path>
            {s.value > 0 && (
              <text
                x={cx}
                y={y - 6}
                textAnchor="middle"
                fontSize={9}
                fill="var(--wa-text-secondary)"
              >
                {copCompact.format(s.value)}
              </text>
            )}
            <text
              x={cx}
              y={PADDING.top + innerH + 14}
              textAnchor="middle"
              fontSize={9}
              fill="var(--wa-text-secondary)"
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
