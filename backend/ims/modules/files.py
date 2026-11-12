"""File upload / download."""

from fastapi import Request, Response, HTTPException, Depends, UploadFile, File
from typing import Optional
import logging
import uuid
import requests as _requests
from ims.repositories import purchase_orders as po_repo
from ims.repositories import files_repo
from ims.repositories import users as users_repo
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
            logging.getLogger("ims").warning("File missing on disk: %s (LOCAL_STORAGE_DIR=%s)", p, LOCAL_STORAGE_DIR)
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


# ---- Profile pictures ---------------------------------------------------------------------------------
AVATAR_MAX_BYTES = 2 * 1024 * 1024


def _image_type(data: bytes) -> Optional[str]:
    """The real image type from the file's first bytes (the file name / declared type are not trusted)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@api_router.post("/auth/me/avatar")
async def upload_my_avatar(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Any signed-in user sets or replaces their own profile picture (PNG, JPEG or WebP, up to 2 MB)."""
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty")
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="The picture is larger than 2 MB")
    ext = _image_type(data)
    if not ext:
        raise HTTPException(status_code=400, detail="Please choose a PNG, JPEG or WebP image")
    fid = str(uuid.uuid4())
    ct = MIME_TYPES.get(ext, "image/jpeg")
    try:
        result = put_object(f"{APP_NAME}/avatars/{user['_id']}/{fid}.{ext}", data, ct)
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger(__name__).exception("Avatar upload failed")
        raise HTTPException(status_code=500, detail=f"Could not store the picture ({type(exc).__name__})")
    await files_repo.insert({
        "id": fid, "storage_path": result["path"], "original_filename": f"avatar.{ext}", "content_type": ct,
        "size": result.get("size", len(data)), "is_deleted": False, "uploaded_by": str(user["_id"]), "created_at": now_iso(),
    })
    old = user.get("avatar_file_id")
    version = now_iso()
    await users_repo.update_fields(user["_id"], {"avatar_file_id": fid, "avatar_version": version})
    if old:
        await files_repo.mark_deleted(old)
    return {"ok": True, "avatar_version": version}


@api_router.delete("/auth/me/avatar")
async def remove_my_avatar(user: dict = Depends(get_current_user)):
    old = user.get("avatar_file_id")
    await users_repo.update_fields(user["_id"], {"avatar_file_id": None, "avatar_version": None})
    if old:
        await files_repo.mark_deleted(old)
    return {"ok": True}


@api_router.get("/users/{user_id}/avatar")
async def get_user_avatar(user_id: str, request: Request, auth: Optional[str] = None):
    """A user's profile picture (any signed-in user may see it). The token may come in `?auth=` so <img> tags work."""
    token = auth or request.cookies.get("access_token")
    if not token:
        h = request.headers.get("Authorization", "")
        token = h[7:] if h.startswith("Bearer ") else None
    if not (token and await user_from_token(token)):
        raise HTTPException(status_code=401, detail="Not authenticated")
    u = await users_repo.get(user_id)
    fid = (u or {}).get("avatar_file_id")
    rec = await files_repo.get(fid) if fid else None
    if not rec:
        raise HTTPException(status_code=404, detail="No profile picture")
    data, ct = get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type", ct), headers={"Cache-Control": "private, max-age=3600"})