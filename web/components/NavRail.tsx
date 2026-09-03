"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

// Rail delgado de navegacion (Fase Contactos, 2026-08-10) -- vive en
// app/(desk)/layout.tsx, por fuera de ConversationSidebar (que ahora solo se
// monta dentro de "(inbox)"). Unico lugar de "Cerrar sesion": antes vivia en
// el header de ConversationSidebar, pero eso lo dejaba inalcanzable desde
// /contacts (donde ese sidebar no se monta) -- centralizado aca para que
// funcione desde cualquier seccion, mismo criterio de "una sola fuente" que
// ya aplica en el resto del proyecto.
//
// Dashboard se agrega aca (Fase Dashboard, 2026-08-10) -- cierra las 3
// piezas del alcance acordado (Contactos, Pipeline, Dashboard). Mismo
// criterio aditivo de siempre: sin placeholders deshabilitados.
const NAV_ITEMS = [
  { href: "/", label: "Inbox", icon: "💬", match: (p: string) => p === "/" || p.startsWith("/conversations") },
  { href: "/contacts", label: "Contactos", icon: "👥", match: (p: string) => p.startsWith("/contacts") },
  { href: "/pipeline", label: "Pipeline", icon: "🔀", match: (p: string) => p.startsWith("/pipeline") },
  { href: "/dashboard", label: "Dashboard", icon: "📊", match: (p: string) => p.startsWith("/dashboard") },
];

export default function NavRail() {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  return (
    <nav className="flex w-16 shrink-0 flex-col items-center border-r border-wa-border bg-wa-header py-3">
      <div className="flex flex-1 flex-col items-center gap-1">
        {NAV_ITEMS.map((item) => {
          const active = item.match(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              className={`flex w-12 flex-col items-center gap-0.5 rounded-lg py-2 text-[10px] ${
                active
                  ? "bg-wa-accent/15 text-wa-accent"
                  : "text-wa-text-secondary hover:bg-wa-hover hover:text-foreground"
              }`}
            >
              <span className="text-lg leading-none">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </div>
      <button
        onClick={handleLogout}
        title="Cerrar sesión"
        className="flex w-12 flex-col items-center gap-0.5 rounded-lg py-2 text-[10px] text-wa-text-secondary hover:bg-wa-hover hover:text-foreground"
      >
        <span className="text-lg leading-none">🚪</span>
        Salir
      </button>
    </nav>
  );
}
