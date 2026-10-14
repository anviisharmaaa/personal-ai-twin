import { useCallback, useRef, useState } from "react";
import Cropper, { type Area } from "react-easy-crop";
import { ApiError, type Twin } from "../lib/api";
import { useDeletePortrait, useUploadPortrait } from "../hooks/useMe";
import { Button, Notice } from "./ui";
import { TwinAvatar } from "./TwinAvatar";

const ACCEPT = ["image/jpeg", "image/png", "image/webp"];

async function cropToBlob(src: string, area: Area): Promise<Blob> {
  const img = await new Promise<HTMLImageElement>((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = () => rej(new Error("Could not read that image."));
    i.src = src;
  });
  const side = Math.min(1024, Math.round(area.width));
  const canvas = document.createElement("canvas");
  canvas.width = side;
  canvas.height = side;
  canvas.getContext("2d")!.drawImage(img, area.x, area.y, area.width, area.height, 0, 0, side, side);
  return new Promise((res, rej) => canvas.toBlob((b) => (b ? res(b) : rej(new Error("Could not prepare the image."))), "image/jpeg", 0.9));
}

export function PortraitEditor({ twin }: { twin: Twin }) {
  const input = useRef<HTMLInputElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [area, setArea] = useState<Area | null>(null);
  const [other, setOther] = useState(false);
  const [permission, setPermission] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const upload = useUploadPortrait();
  const del = useDeletePortrait();
  const onArea = useCallback((_: Area, px: Area) => setArea(px), []);

  const pick = (f: File | undefined) => {
    setError(null);
    if (!f) return;
    if (!ACCEPT.includes(f.type)) return setError("Please choose a JPEG, PNG or WebP image.");
    if (f.size > 15 * 1024 * 1024) return setError("That image is very large. Please choose one under 15 MB.");
    setSrc(URL.createObjectURL(f));
    setZoom(1);
    setCrop({ x: 0, y: 0 });
  };

  const close = () => {
    if (src) URL.revokeObjectURL(src);
    setSrc(null);
    setOther(false);
    setPermission(false);
    if (input.current) input.current.value = "";
  };

  const save = async () => {
    if (!src || !area) return;
    setError(null);
    try {
      const blob = await cropToBlob(src, area);
      await upload.mutateAsync({ blob, other, permission });
      close();
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Upload failed.");
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-6">
        <TwinAvatar twin={twin} size={120} orbit={false} />
        <div className="space-y-2">
          <p className="max-w-sm text-sm text-muted">
            A portrait is just an image. It does not create a voice or an animated avatar, and it is not proof of identity. Stored privately; only you can see it.
          </p>
          <div className="flex flex-wrap gap-2">
            <input ref={input} type="file" accept={ACCEPT.join(",")} className="sr-only" aria-label="Choose portrait file"
              onChange={(e) => pick(e.target.files?.[0])} />
            <Button variant="secondary" size="sm" onClick={() => input.current?.click()}>
              {twin.portrait_url ? "Replace portrait" : "Upload portrait"}
            </Button>
            {twin.portrait_path && <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>Delete portrait</Button>}
          </div>
        </div>
      </div>
      {error && !src && <div className="mt-3"><Notice tone="error">{error}</Notice></div>}

      {src && (
        <div role="dialog" aria-modal="true" aria-label="Crop portrait" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-[24px] border border-border bg-surface p-5">
            <div className="relative h-72 overflow-hidden rounded-[16px] bg-surface-2">
              <Cropper image={src} crop={crop} zoom={zoom} aspect={1} cropShape="round" showGrid={false}
                onCropChange={setCrop} onZoomChange={setZoom} onCropComplete={onArea} />
            </div>
            <label className="mt-4 block text-sm font-medium" htmlFor="zoom">Zoom</label>
            <input id="zoom" type="range" min={1} max={3} step={0.05} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} className="w-full accent-[var(--accent)]" />
            <div className="mt-3 space-y-2 text-sm">
              <label className="flex items-start gap-2"><input type="checkbox" checked={other} onChange={(e) => { setOther(e.target.checked); if (!e.target.checked) setPermission(false); }} className="mt-1" />
                This portrait shows someone other than me</label>
              {other && <label className="flex items-start gap-2"><input type="checkbox" checked={permission} onChange={(e) => setPermission(e.target.checked)} className="mt-1" />
                I have this person's permission to use their portrait here</label>}
            </div>
            {error && <div className="mt-3"><Notice tone="error">{error}</Notice></div>}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={close}>Cancel</Button>
              <Button onClick={save} loading={upload.isPending} disabled={!area || (other && !permission)}>Save portrait</Button>
            </div>
          </div>
        </div>
      )}

      {confirmDelete && (
        <div role="alertdialog" aria-modal="true" aria-label="Delete portrait" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
          <div className="w-full max-w-sm rounded-[24px] border border-border bg-surface p-6">
            <h3 className="text-lg font-semibold">Delete this portrait?</h3>
            <p className="mt-2 text-sm text-muted">The image is removed from private storage. You can upload another any time.</p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Keep it</Button>
              <Button variant="danger" loading={del.isPending} onClick={async () => { await del.mutateAsync().catch(() => {}); setConfirmDelete(false); }}>Delete</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
