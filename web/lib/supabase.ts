import { createClient } from "@supabase/supabase-js";

// Unica fuente de verdad del cliente de Supabase para el navegador. Cualquier
// pagina/componente que necesite hablarle a Supabase importa este modulo --
// nunca crea su propio createClient() con las variables de entorno copiadas
// a mano (ver "Lineamiento permanente" en ARCHITECTURE.md).
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error(
    "Faltan NEXT_PUBLIC_SUPABASE_URL o NEXT_PUBLIC_SUPABASE_ANON_KEY -- revisa .env.local"
  );
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
