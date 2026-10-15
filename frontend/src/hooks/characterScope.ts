import { createContext, useContext } from "react";

/** Which character the editors below are acting on. `null` means the personal self-twin (the original behaviour). */
export const CharacterScopeContext = createContext<string | null>(null);
export const useCharacterScope = () => useContext(CharacterScopeContext);
export const withCharacter = (path: string, id: string | null) => (id ? `${path}?character_id=${encodeURIComponent(id)}` : path);
