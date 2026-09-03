// Avatar con iniciales -- no hay foto de perfil real disponible (WhatsApp
// Cloud API no expone la foto del contacto en este proyecto). El color se
// deriva de un hash simple del telefono, para que cada contacto tenga
// siempre el mismo color entre la lista y el header del hilo, sin guardar
// nada nuevo en la base ni depender de un id secuencial.

const AVATAR_COLORS = [
  "#008069", // verde WhatsApp, primero a proposito (el mas frecuente visualmente)
  "#7C5CBF",
  "#D9A73B",
  "#C4536F",
  "#3B84C4",
  "#4B9E6E",
  "#B15FBF",
  "#C46B3B",
];

export function initials(name: string | null, phone: string): string {
  const source = name?.trim() || phone;
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function avatarColor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}
