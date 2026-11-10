"""Meta lists, departments, categories and the product catalog."""

from fastapi import HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Literal, Dict
from ims.ids import ObjectId
from ims.repositories import departments as dept_repo
from ims.repositories import categories as cat_repo
from ims.repositories import products as prod_repo
from ims.repositories import assets as asset_repo
from ims.common import (
    ALL_MENU_KEYS,
    MENU,
    PRODUCT_TYPE_LABELS,
    ROLES,
    ROLE_LABELS,
    _clean_brand,
    _department_is_it,
    _pkey,
    _skey,
    _tracked_by_quantity,
    api_router,
    get_current_user,
    now_iso,
    require_roles,
)

class DepartmentIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None


class CategoryIn(BaseModel):
    name: str
    department_id: Optional[str] = None
    description: Optional[str] = None


@api_router.get("/meta/roles")
async def meta_roles(user: dict = Depends(get_current_user)):
    return {"roles": [{"value": r, "label": ROLE_LABELS[r]} for r in ROLES]}


@api_router.get("/meta/menu")
async def meta_menu(user: dict = Depends(get_current_user)):
    hidden = ("report-center", "my-reports", "corrections", "my-corrections")       # granted per report / Super Admin only, never per role
    menu = [{**g, "items": [i for i in g["items"] if i["key"] not in hidden]} for g in MENU]
    return {"menu": [g for g in menu if g["items"]], "keys": [k for k in ALL_MENU_KEYS if k not in hidden]}


@api_router.get("/departments")
async def list_departments(user: dict = Depends(get_current_user)):
    docs = await dept_repo.list_all()
    return [{"id": str(d["_id"]), "name": d["name"], "code": d.get("code"), "description": d.get("description")} for d in docs]


@api_router.post("/departments")
async def create_department(payload: DepartmentIn, user: dict = Depends(require_roles("super_admin"))):
    doc = payload.model_dump()
    doc["created_at"] = now_iso()
    new_id = await dept_repo.insert(doc)
    return {"id": str(new_id), **payload.model_dump()}


@api_router.put("/departments/{dept_id}")
async def update_department(dept_id: str, payload: DepartmentIn, user: dict = Depends(require_roles("super_admin"))):
    await dept_repo.update_fields(dept_id, payload.model_dump())
    return {"id": dept_id, **payload.model_dump()}


@api_router.delete("/departments/{dept_id}")
async def delete_department(dept_id: str, user: dict = Depends(require_roles("super_admin"))):
    await dept_repo.delete(dept_id)
    return {"ok": True}


@api_router.get("/categories")
async def list_categories(user: dict = Depends(get_current_user)):
    docs = await cat_repo.list_all()
    out = []
    for c in docs:
        dept_name = None
        if c.get("department_id") and ObjectId.is_valid(c["department_id"]):
            d = await dept_repo.get(c["department_id"])
            dept_name = d["name"] if d else None
        out.append({"id": str(c["_id"]), "name": c["name"], "department_id": c.get("department_id"),
                    "department_name": dept_name, "description": c.get("description")})
    return out


@api_router.post("/categories")
async def create_category(payload: CategoryIn, user: dict = Depends(require_roles("super_admin"))):
    doc = payload.model_dump()
    doc["created_at"] = now_iso()
    new_id = await cat_repo.insert(doc)
    return {"id": str(new_id), **payload.model_dump()}


@api_router.put("/categories/{cat_id}")
async def update_category(cat_id: str, payload: CategoryIn, user: dict = Depends(require_roles("super_admin"))):
    await cat_repo.update_fields(cat_id, payload.model_dump())
    return {"id": cat_id, **payload.model_dump()}


@api_router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, user: dict = Depends(require_roles("super_admin"))):
    await cat_repo.delete(cat_id)
    return {"ok": True}


class ProductIn(BaseModel):
    name: str
    product_type: Literal["asset", "consumable", "it_accessories", "network", "furniture"]
    brand: Optional[str] = None      # optional default brand (pre-fills the Handover / GRN forms)


async def _available_counts() -> Dict[str, int]:
    """Available units for EVERY product in one pass, keyed by _skey(asset name)."""
    out: Dict[str, int] = {}
    for name, n in (await asset_repo.available_counts()).items():
        k = _skey(name)
        out[k] = out.get(k, 0) + n
    return out


def _product_out(d: dict, in_stock: int) -> dict:
    """The one product shape every screen relies on (Products, Stock GRN, Handover, forms)."""
    ptype = d.get("product_type")
    return {
        "id": str(d["_id"]), "name": d["name"], "product_type": ptype,
        "category_name": PRODUCT_TYPE_LABELS.get(ptype, "Other"),
        "brand": d.get("brand") or None,
        "tracked_by_quantity": _tracked_by_quantity(d),
        "in_stock": in_stock,
    }


async def _can_manage_products(user: dict) -> bool:
    if user["role"] == "super_admin":
        return True
    return user["role"] == "dept_head" and await _department_is_it(user.get("department_id"))


@api_router.get("/products")
async def list_products(product_type: Optional[str] = None, user: dict = Depends(get_current_user)):
    docs = await prod_repo.list_all(product_type=product_type)
    counts = await _available_counts()
    return [_product_out(d, counts.get(_skey(d["name"]), 0)) for d in docs]


@api_router.get("/products/{pid}/units")
async def product_units(pid: str, user: dict = Depends(get_current_user)):
    """The individual units of one product that can be issued right now (in stock, not reserved
    by another slip) - drives the unit picker on the Handover form. Oldest stock first.
    Quantity-tracked products (consumables) have no units to pick: only the count is returned."""
    if not ObjectId.is_valid(pid):
        raise HTTPException(status_code=404, detail="Product not found")
    prod = await prod_repo.get(pid)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    by_qty = _tracked_by_quantity(prod)
    in_stock = await asset_repo.count_available(prod["name"])
    units: List[dict] = []
    if not by_qty:
        docs = await asset_repo.list_available(prod["name"], limit=5000)
        units = [{"id": str(a["_id"]), "name": a.get("name"), "tag_id": a.get("tag_id"),
                  "serial_no": a.get("serial_no"), "brand": a.get("brand") or None} for a in docs]
    return {"product_id": pid, "name": prod["name"], "tracked_by_quantity": by_qty,
            "in_stock": in_stock, "units": units}


@api_router.post("/products")
async def create_product(payload: ProductIn, user: dict = Depends(get_current_user)):
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(status_code=400, detail="Product name is required")
    if await prod_repo.get_by_name_key(_pkey(name)):
        raise HTTPException(status_code=400, detail=f"'{name}' already exists in the catalog")
    doc = {"name": name, "name_key": _pkey(name), "product_type": payload.product_type,
           "brand": _clean_brand(payload.brand),
           "created_by": user["name"], "created_at": now_iso()}
    new_id = await prod_repo.insert(doc)
    doc["_id"] = new_id
    return _product_out(doc, await asset_repo.count_available(name))


class ProductBulkIn(BaseModel):
    product_type: Literal["asset", "consumable", "it_accessories", "network", "furniture"]
    names: List[str]


@api_router.post("/products/bulk")
async def bulk_create_products(payload: ProductBulkIn, user: dict = Depends(get_current_user)):
    """Add many products of one type at once (one name per entry). Duplicates - including
    case/space variants of existing names - are skipped, not errors."""
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    added, skipped, seen = [], [], set()
    for raw in payload.names:
        name = " ".join((raw or "").split())
        if not name:
            continue
        key = _pkey(name)
        if key in seen or await prod_repo.get_by_name_key(key):
            skipped.append(name)
            continue
        seen.add(key)
        await prod_repo.insert({"name": name, "name_key": key, "product_type": payload.product_type,
                               "created_by": user["name"], "created_at": now_iso()})
        added.append(name)
    return {"added": len(added), "skipped": len(skipped), "skipped_names": skipped}


@api_router.put("/products/{pid}")
async def update_product(pid: str, payload: ProductIn, user: dict = Depends(get_current_user)):
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    if not ObjectId.is_valid(pid) or not await prod_repo.get(pid):
        raise HTTPException(status_code=404, detail="Product not found")
    name = " ".join(payload.name.split())
    clash = await prod_repo.get_by_name_key(_pkey(name))
    if clash and str(clash["_id"]) == pid:
        clash = None
    if not name or clash:
        raise HTTPException(status_code=400, detail=f"'{name}' already exists in the catalog" if clash else "Product name is required")
    upd = {"name": name, "name_key": _pkey(name), "product_type": payload.product_type}
    if payload.brand is not None:          # omitted -> keep the current brand; "" -> clear it
        upd["brand"] = _clean_brand(payload.brand)
    await prod_repo.update_fields(pid, upd)
    fresh = await prod_repo.get(pid)
    return _product_out(fresh, await asset_repo.count_available(name))


@api_router.delete("/products/{pid}")
async def delete_product(pid: str, user: dict = Depends(get_current_user)):
    if not await _can_manage_products(user):
        raise HTTPException(status_code=403, detail="Only Super Admin / IT Head can manage the product catalog")
    if ObjectId.is_valid(pid):
        await prod_repo.delete(pid)
    return {"ok": True}
