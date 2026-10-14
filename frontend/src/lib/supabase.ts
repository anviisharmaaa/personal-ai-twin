import { createClient } from "@supabase/supabase-js";
import { config } from "./config";

// Browser client uses ONLY the publishable key. The service-role key never reaches the browser.
export const supabase = createClient(
  config.supabaseUrl || "http://localhost:54321",
  config.supabaseKey || "missing-key",
  { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } },
);
