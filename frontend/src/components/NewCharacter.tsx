import { useState } from "react";
import { ApiError } from "../lib/api";
import { useCreateCharacter } from "../hooks/useMe";
import { Button, Card, Notice, TextArea, TextField } from "./ui";

/** Create another, separate character (its own description, portrait, profile, memories and conversations). */
export function NewCharacter({ onCreated, onCancel }: { onCreated: (id: string) => void; onCancel: () => void }) {
  const create = useCreateCharacter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    if (!name.trim()) return setErr("Give the character a name.");
    try {
      const res = await create.mutateAsync({ name: name.trim(), description: description.trim() || undefined });
      onCreated(res.twin.id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Couldn’t create the character. Your text is still here — try again.");
    }
  };

  return (
    <Card className="mt-6">
      <form aria-label="New character" className="space-y-5" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <div>
          <h2 className="text-lg font-semibold">New character</h2>
          <p className="mt-1 text-sm text-muted">A separate character with its own description, portrait, profile, memories and conversations. It never shares them with your other characters.</p>
        </div>
        <TextField label="Character’s name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus />
        <TextArea label="Description (optional now)" value={description} maxLength={8000} rows={6}
          onChange={(e) => setDescription(e.target.value)}
          hint="Who they are and how they talk and behave. Every reply is guided by this. You can write or refine it later in the Character tab." />
        {err && <Notice tone="error">{err}</Notice>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create character</Button>
        </div>
      </form>
    </Card>
  );
}
