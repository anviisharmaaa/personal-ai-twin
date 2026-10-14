import { useQueryClient } from "@tanstack/react-query";
import type { Session } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { supabase } from "../lib/supabase";

type AuthState = { session: Session | null; loading: boolean; signOut: () => Promise<void> };
const Ctx = createContext<AuthState>({ session: null, loading: true, signOut: async () => {} });
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  useEffect(() => {
    let lastUser: string | null = null;
    supabase.auth.getSession().then(({ data }) => {
      lastUser = data.session?.user.id ?? null;
      setSession(data.session);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      const uid = s?.user.id ?? null;
      // Server state belongs to one account: drop every cache on logout or account change.
      if (uid !== lastUser) qc.clear();
      lastUser = uid;
      setSession(s);
      setLoading(false);
    });
    return () => sub.subscription.unsubscribe();
  }, [qc]);

  const signOut = async () => {
    await supabase.auth.signOut();
    qc.clear();
  };

  return <Ctx.Provider value={{ session, loading, signOut }}>{children}</Ctx.Provider>;
}
