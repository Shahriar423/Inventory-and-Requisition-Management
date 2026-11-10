// Phone photos are often 4-8 MB. Shrink them in the browser before upload (max 2000 px, JPEG 82%),
// keeping the original file NAME so spreadsheet references still match. PDFs and small files pass through.
const MAX_SIDE = 2000;
const SKIP_BELOW = 900 * 1024;

export async function compressImage(file) {
  try {
    if (!file.type.startsWith("image/") || file.type === "image/gif" || file.size < SKIP_BELOW) return file;
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";           // PNG transparency -> white, not black
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close?.();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name, { type: "image/jpeg", lastModified: file.lastModified });
  } catch (e) {
    return file;                           // never block an upload because compression failed
  }
}

export async function compressAll(files) {
  const out = [];
  for (const f of files) out.push(await compressImage(f));
  return out;
}
