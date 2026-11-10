"""File upload / download."""

from fastapi import Request, Response, HTTPException, Depends, UploadFile, File
from typing import Optional
import logging
import uuid
import requests as _requests
from ims.repositories import purchase_orders as po_repo
from ims.repositories import files_repo
from ims.common import (
    APP_NAME,
    LOCAL_STORAGE_DIR,
    MIME_TYPES,
    STORAGE_URL,
    _fallback_file,
    _local_file,
    api_router,
    can_view_po_quotes,
    get_current_user,
    init_storage,
    now_iso,
    put_object,
    user_from_token,
)

def get_object(path: str):
    if LOCAL_STORAGE_DIR:
        p = _local_file(path)
        if not p.is_file():
            raise HTTPException(status_code=404, detail="File not found on the server")
        return p.read_bytes(), MIME_TYPES.get(p.suffix.lstrip(".").lower(), "application/octet-stream")
    fb = _fallback_file(path)
    if fb.is_file():                       # saved locally while remote storage was unavailable
        return fb.read_bytes(), MIME_TYPES.get(fb.suffix.lstrip(".").lower(), "application/octet-stream")
    key = init_storage()
    r = _requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if r.status_code == 404:
        key = init_storage(force=True)
        r = _requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "application/octet-stream")


@api_router.post("/files/upload")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    fid = str(uuid.uuid4())
    path = f"{APP_NAME}/uploads/{user['_id']}/{fid}.{ext}"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty")
    ct = file.content_type or MIME_TYPES.get(ext, "application/octet-stream")
    try:
        result = put_object(path, data, ct)
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger(__name__).exception("File upload failed")
        raise HTTPException(status_code=500, detail=f"Could not store the file on the server ({type(exc).__name__}). Please contact the administrator.")
    doc = {
        "id": fid, "storage_path": result["path"], "original_filename": file.filename,
        "content_type": ct, "size": result.get("size", len(data)), "is_deleted": False,
        "uploaded_by": str(user["_id"]), "created_at": now_iso(),
    }
    await files_repo.insert(doc)
    return {"id": fid, "original_filename": file.filename, "size": doc["size"], "content_type": ct}


@api_router.get("/files/{file_id}/download")
async def download_file(file_id: str, request: Request, auth: Optional[str] = None):
    token = auth or request.cookies.get("access_token")
    if not token:
        h = request.headers.get("Authorization", "")
        token = h[7:] if h.startswith("Bearer ") else None
    viewer = await user_from_token(token) if token else None
    if not viewer:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rec = await files_repo.get(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    # Vendor quotation PDFs attached to a PO: Purchase Head (+ uploader / Super Admin) only.
    for po in await po_repo.list_with_quote_file(file_id):
        if not await can_view_po_quotes(po, viewer):
            raise HTTPException(status_code=403, detail="Vendor quotations can only be viewed by the Purchase Head")
    data, ct = get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type", ct),
                    headers={"Content-Disposition": f'inline; filename="{rec["original_filename"]}"'})
