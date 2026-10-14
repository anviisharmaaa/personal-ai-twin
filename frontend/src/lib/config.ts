export const config = {
  apiUrl: (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000",
  supabaseUrl: (import.meta.env.VITE_SUPABASE_URL as string | undefined) ?? "",
  supabaseKey: (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) ?? "",
};

export const isConfigured = Boolean(config.supabaseUrl && config.supabaseKey);
