"""Backend regression tests for IMS - IT Requisition & Asset Management System."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()
API = f"{BASE_URL}/api"

SUPER_ADMIN = ("adolfhitlerrr64@gmail.com", "admin123")
IT_HEAD = ("ashik@gmail.com", "password123")
ACCOUNTS = ("sk@gmail.com", "password123")
MD_USER = ("md@gmail.com", "password123")
PR_EXEC = ("baitulla@gmail.com", "password123")
HR_HEAD = ("maruf@gmail.com", "password123")
PURCHASE_HEAD = ("shuvo@gmail.com", "password123")


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    data = r.json()
    # cookies + bearer support
    token = data.get("access_token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s, data


@pytest.fixture(scope="session")
def admin():
    s, data = _login(*SUPER_ADMIN)
    return {"session": s, "user": data["user"]}


@pytest.fixture(scope="session")
def pr_exec():
    s, data = _login(*PR_EXEC)
    return {"session": s, "user": data["user"]}


@pytest.fixture(scope="session")
def it_head():
    s, data = _login(*IT_HEAD)
    return {"session": s, "user": data["user"]}


# --------------------------- Auth ---------------------------
class TestAuth:
    def test_login_success_sets_cookie_and_token(self):
        r = requests.post(f"{API}/auth/login", json={"email": SUPER_ADMIN[0], "password": SUPER_ADMIN[1]})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data and isinstance(data["access_token"], str)
        assert data["user"]["email"] == SUPER_ADMIN[0]
        assert data["user"]["role"] == "super_admin"
        # httpOnly cookie set
        set_cookie = r.headers.get("set-cookie", "")
        assert "access_token" in set_cookie
        assert "HttpOnly" in set_cookie

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login", json={"email": SUPER_ADMIN[0], "password": "wrong"})
        assert r.status_code == 401

    def test_me_requires_auth(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_ok(self, admin):
        r = admin["session"].get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == SUPER_ADMIN[0]

    def test_permissions_super_admin_sees_all(self, admin):
        r = admin["session"].get(f"{API}/auth/permissions")
        assert r.status_code == 200
        data = r.json()
        assert len(data["allowed"]) == 15, data["allowed"]
        assert len(data["menu"]) == 7

    def test_permissions_executive_limited(self, pr_exec):
        r = pr_exec["session"].get(f"{API}/auth/permissions")
        assert r.status_code == 200
        allowed = r.json()["allowed"]
        assert "users-roles" not in allowed
        assert "new-requisition" in allowed


# --------------------------- RBAC ---------------------------
class TestRBAC:
    def test_non_admin_cannot_list_permissions(self, pr_exec):
        r = pr_exec["session"].get(f"{API}/permissions")
        assert r.status_code == 403

    def test_non_admin_cannot_create_user(self, pr_exec):
        r = pr_exec["session"].post(f"{API}/users", json={"name": "x", "email": "x@x.com", "role": "executive"})
        assert r.status_code == 403


# --------------------------- Users CRUD ---------------------------
class TestUsersCRUD:
    def test_list_users(self, admin):
        r = admin["session"].get(f"{API}/users")
        assert r.status_code == 200
        emails = [u["email"] for u in r.json()]
        assert SUPER_ADMIN[0] in emails
        assert "ashik@gmail.com" in emails

    def test_create_edit_delete_user(self, admin):
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        # CREATE
        r = admin["session"].post(f"{API}/users", json={
            "name": "TEST User", "email": email, "password": "pass1234",
            "role": "executive", "can_raise_pr": True,
        })
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
        # GET verify
        r2 = admin["session"].get(f"{API}/users")
        assert any(u["email"] == email for u in r2.json())
        # UPDATE
        r3 = admin["session"].put(f"{API}/users/{uid}", json={"name": "TEST Updated"})
        assert r3.status_code == 200
        assert r3.json()["name"] == "TEST Updated"
        # DELETE
        r4 = admin["session"].delete(f"{API}/users/{uid}")
        assert r4.status_code == 200

    def test_cannot_delete_self(self, admin):
        me = admin["user"]["id"]
        r = admin["session"].delete(f"{API}/users/{me}")
        assert r.status_code == 400


# --------------------------- Departments / Categories ---------------------------
class TestDeptCat:
    def test_departments_seeded(self, admin):
        r = admin["session"].get(f"{API}/departments")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()]
        for n in ["IT", "HR", "Accounts", "Purchase", "Primitek Group"]:
            assert n in names

    def test_department_crud(self, admin):
        name = f"TEST_D_{uuid.uuid4().hex[:6]}"
        r = admin["session"].post(f"{API}/departments", json={"name": name, "code": "T"})
        assert r.status_code == 200
        did = r.json()["id"]
        r = admin["session"].put(f"{API}/departments/{did}", json={"name": name + "_u", "code": "T2"})
        assert r.status_code == 200
        r = admin["session"].delete(f"{API}/departments/{did}")
        assert r.status_code == 200

    def test_category_crud(self, admin):
        r = admin["session"].post(f"{API}/categories", json={"name": f"TEST_C_{uuid.uuid4().hex[:6]}"})
        assert r.status_code == 200
        cid = r.json()["id"]
        r = admin["session"].delete(f"{API}/categories/{cid}")
        assert r.status_code == 200


# --------------------------- Requisitions & chains ---------------------------
class TestApprovalChains:
    def test_product_high_value_chain_5_levels_with_md(self, pr_exec):
        payload = {
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Laptop", "quantity": 1, "rate": 60000}],
            "requester_note": "TEST high value",
        }
        r = pr_exec["session"].post(f"{API}/requisitions", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_amount"] == 60000
        assert d["status"] == "pending_dept"
        assert d["requisition_no"].startswith(f"REQ-{time.strftime('%Y')}-")
        chain = d["approval_chain"]
        assert len(chain) == 5
        labels = [s["label"] for s in chain]
        assert "Managing Director" in labels
        assert labels[-1] == "Purchase Head"
        assert chain[-1]["approver_name"] == "Shuvo"

    def test_product_low_value_chain_4_levels_no_md(self, pr_exec):
        payload = {
            "requisition_type": "product",
            "items": [{"product_type": "consumable", "product_name": "TEST Mouse", "quantity": 2, "rate": 500}],
        }
        r = pr_exec["session"].post(f"{API}/requisitions", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert d["total_amount"] == 1000
        chain = d["approval_chain"]
        assert len(chain) == 4
        labels = [s["label"] for s in chain]
        assert "Managing Director" not in labels
        assert labels[-1] == "Purchase Head"
        assert d["status"] == "pending_dept"

    def test_service_chain_single_level(self, pr_exec):
        payload = {
            "requisition_type": "service",
            "items": [{"product_type": "consumable", "product_name": "TEST Repair", "quantity": 1, "rate": 200}],
        }
        r = pr_exec["session"].post(f"{API}/requisitions", json=payload)
        assert r.status_code == 200
        d = r.json()
        chain = d["approval_chain"]
        assert len(chain) == 1
        assert chain[0]["label"] == "IT Department Head"
        assert chain[0]["approver_name"] == "Ashik Chowdhury"
        assert d["status"] == "pending_it_service"

    def test_non_pr_user_forbidden(self):
        s, _ = _login("dipto@gmail.com", "password123")
        r = s.post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "x", "quantity": 1, "rate": 100}],
        })
        assert r.status_code == 403


class TestApproveFlow:
    def test_approve_advances_status(self, pr_exec, it_head):
        # Create a product low-value requisition (raised by IT executive)
        # Its first approver = Dept Head of IT (Ashik)
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Keyboard", "quantity": 1, "rate": 1000}],
        })
        assert r.status_code == 200
        req = r.json()
        req_id = req["id"]
        assert req["status"] == "pending_dept"
        # Ashik is IT dept head; also level-1 approver for IT executive requesters
        # List approve queue
        rq = it_head["session"].get(f"{API}/requisitions?scope=approve")
        assert rq.status_code == 200
        ids = [x["id"] for x in rq.json()]
        assert req_id in ids
        # Approve
        act = it_head["session"].post(f"{API}/requisitions/{req_id}/action",
                                       json={"action": "approve", "note": "ok"})
        assert act.status_code == 200, act.text
        # Since Ashik is also level-2 (IT Head), status may advance to next step (pending_it or pending_accounts)
        assert act.json()["status"] in ("pending_it", "pending_accounts", "pending_md", "pending_purchase")

    def test_reject_flow(self, pr_exec, it_head):
        # For step 2, service requisitions cannot use /action; use product instead.
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "consumable", "product_name": "TEST Reject", "quantity": 1, "rate": 100}],
        })
        rid = r.json()["id"]
        act = it_head["session"].post(f"{API}/requisitions/{rid}/action",
                                       json={"action": "reject", "note": "no"})
        assert act.status_code == 200
        assert act.json()["status"] == "rejected"

    def test_action_on_service_rejected_400(self, pr_exec, it_head):
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "service",
            "items": [{"product_type": "consumable", "product_name": "TEST SvcAction", "quantity": 1, "rate": 100}],
        })
        rid = r.json()["id"]
        act = it_head["session"].post(f"{API}/requisitions/{rid}/action",
                                       json={"action": "approve", "note": "x"})
        assert act.status_code == 400


class TestListsAndStats:
    def test_scopes_mine_pending_history(self, pr_exec):
        for scope in ("mine", "pending", "history", "all"):
            r = pr_exec["session"].get(f"{API}/requisitions?scope={scope}")
            assert r.status_code == 200
            assert isinstance(r.json(), list)

    def test_dashboard_stats(self, admin):
        r = admin["session"].get(f"{API}/dashboard/stats")
        assert r.status_code == 200
        d = r.json()
        for k in ("total", "pending", "approved", "rejected", "high_value", "my_queue", "recent"):
            assert k in d


class TestPermissionsMgmt:
    def test_toggle_permissions(self, admin):
        # get current dept_head perms
        r = admin["session"].get(f"{API}/permissions")
        assert r.status_code == 200
        rows = r.json()
        dh = next(x for x in rows if x["role"] == "dept_head")
        original = list(dh["items"])
        new_items = original[:-1] if original else []
        r2 = admin["session"].put(f"{API}/permissions/dept_head", json={"items": new_items})
        assert r2.status_code == 200
        assert set(r2.json()["items"]) == set(new_items)
        # restore
        admin["session"].put(f"{API}/permissions/dept_head", json={"items": original})


# =========================== STEP 2 FEATURES ==========================
import io as _io


class TestFilesUploadDownload:
    def test_upload_and_download(self, pr_exec):
        payload = b"hello test file content"
        files = {"file": ("test_note.txt", _io.BytesIO(payload), "text/plain")}
        r = pr_exec["session"].post(f"{API}/files/upload", files=files)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["original_filename"] == "test_note.txt"
        assert d["size"] == len(payload)
        fid = d["id"]
        # Download
        r2 = pr_exec["session"].get(f"{API}/files/{fid}/download")
        assert r2.status_code == 200
        assert r2.content == payload

    def test_download_requires_auth(self):
        r = requests.get(f"{API}/files/nonexistent/download")
        assert r.status_code == 401


class TestServiceWorkflow:
    def test_service_transition_full_flow(self, pr_exec, it_head):
        # Create service requisition
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "service",
            "items": [{"product_type": "consumable", "product_name": "TEST SvcFlow", "quantity": 1, "rate": 100}],
        })
        assert r.status_code == 200
        rid = r.json()["id"]
        assert r.json()["status"] == "pending_it_service"

        # Advance step-by-step as IT head
        expected = ["product_collected_by_it", "sent_to_service_center", "service_completed_and_returned"]
        for exp in expected:
            r2 = it_head["session"].post(f"{API}/requisitions/{rid}/service-transition", json={})
            assert r2.status_code == 200, r2.text
            assert r2.json()["status"] == exp
        # Now closed -> further transition should 400
        r3 = it_head["session"].post(f"{API}/requisitions/{rid}/service-transition", json={})
        assert r3.status_code == 400

    def test_service_transition_forbidden_for_others(self, pr_exec):
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "service",
            "items": [{"product_type": "consumable", "product_name": "TEST SvcForbid", "quantity": 1, "rate": 100}],
        })
        rid = r.json()["id"]
        # Requester (executive) is not IT head nor super_admin -> should be 403
        r2 = pr_exec["session"].post(f"{API}/requisitions/{rid}/service-transition", json={})
        assert r2.status_code == 403


class TestPurchaseRequisitionPDF:
    def test_pdf_returns_bytes_and_assigns_pr_no(self, pr_exec):
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST PDF", "quantity": 1, "rate": 1234}],
            "requester_note": "TEST pdf",
        })
        rid = r.json()["id"]
        r2 = pr_exec["session"].get(f"{API}/requisitions/{rid}/pdf")
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("application/pdf")
        assert r2.content[:4] == b"%PDF"
        # verify PR number stored and starts with LPRIT-YYYYMM
        r3 = pr_exec["session"].get(f"{API}/requisitions/{rid}")
        pr_no = r3.json().get("purchase_pr_no")
        assert pr_no and pr_no.startswith("LPRIT-")
        assert len(pr_no.split("-")[1]) == 10  # YYYYMM + 4 digits


class TestAssetsAndGRN:
    def test_grn_creates_assets_and_shows_in_stock(self, admin):
        challan = f"CH-{uuid.uuid4().hex[:6]}"
        payload = {
            "challan_no": challan, "vendor_name": "TEST Vendor",
            "items": [{
                "product_name": "TEST Laptop", "uom": "Nos", "quantity": 2, "rate": 45000,
                "assets": [
                    {"serial_no": f"SN-{uuid.uuid4().hex[:6]}", "tag_id": f"TAG-{uuid.uuid4().hex[:6]}"},
                    {"serial_no": f"SN-{uuid.uuid4().hex[:6]}", "tag_id": f"TAG-{uuid.uuid4().hex[:6]}"},
                ],
            }],
        }
        r = admin["session"].post(f"{API}/grns", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["grn_no"].startswith("GRN-")
        assert d["created_assets"] == 2
        # verify assets visible
        r2 = admin["session"].get(f"{API}/assets?status=in_stock")
        assert r2.status_code == 200
        names = [a["name"] for a in r2.json()]
        assert "TEST Laptop" in names

    def test_grn_rbac_denied_for_executive(self, pr_exec):
        r = pr_exec["session"].post(f"{API}/grns", json={
            "challan_no": "X", "vendor_name": "X",
            "items": [{"product_name": "x", "quantity": 1, "rate": 1, "assets": []}],
        })
        assert r.status_code == 403


class TestHandovers:
    def test_handover_reserves_asset_until_confirmed(self, admin):
        # Step 3/4 contract: handover keeps asset in_stock w/ pending_receipt=True.
        challan = f"CH-{uuid.uuid4().hex[:6]}"
        sn = f"SN-{uuid.uuid4().hex[:8]}"
        r = admin["session"].post(f"{API}/grns", json={
            "challan_no": challan, "vendor_name": "TEST V2",
            "items": [{"product_name": "TEST Monitor", "quantity": 1, "rate": 15000,
                       "assets": [{"serial_no": sn, "tag_id": f"TAG-{uuid.uuid4().hex[:6]}"}]}],
        })
        assert r.status_code == 200
        r2 = admin["session"].get(f"{API}/assets?status=in_stock")
        asset = next(a for a in r2.json() if a.get("serial_no") == sn)
        aid = asset["id"]

        hr = admin["session"].post(f"{API}/handovers", json={
            "type": "handover", "employee_name": "Baitulla",  # matches seeded user
            "items": [{"item": "TEST Monitor", "quantity": 1, "asset_id": aid}],
            "prepared_by_sign": "data:image/png;base64,AAAA",
            "received_by_sign": "data:image/png;base64,BBBB",
        })
        assert hr.status_code == 200, hr.text
        hd = hr.json()
        assert hd["slip_no"].startswith("HO-")
        assert hd["prepared_by_sign"] == "data:image/png;base64,AAAA"

        # Asset must still be in_stock (pending receipt) - central stock NOT deducted yet
        r3 = admin["session"].get(f"{API}/assets?status=in_stock")
        this_asset = next((a for a in r3.json() if a["id"] == aid), None)
        assert this_asset is not None, "asset should remain in_stock until confirmation"
        assert this_asset["status"] == "in_stock"
        assert this_asset.get("pending_receipt") is True

        # Takeover: return an assigned asset (create one directly for takeover test)
        # First force-assign via confirmation to have something to take back
        # We'll cover takeover via a separate flow below by confirming this notification first.


class TestNotificationsFlow:
    def test_notification_created_and_confirm_deducts_stock(self, admin):
        # New GRN -> tagged asset
        sn = f"SN-{uuid.uuid4().hex[:8]}"
        r = admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST V3",
            "items": [{"product_name": "TEST Notif Laptop", "quantity": 1, "rate": 40000,
                       "assets": [{"serial_no": sn, "tag_id": f"TAG-{uuid.uuid4().hex[:6]}"}]}],
        })
        assert r.status_code == 200
        assets = admin["session"].get(f"{API}/assets?status=in_stock").json()
        aid = next(a["id"] for a in assets if a.get("serial_no") == sn)

        # Handover to Baitulla (seeded user) - login as baitulla to see notifs
        hr = admin["session"].post(f"{API}/handovers", json={
            "type": "handover", "employee_name": "Baitulla",
            "items": [{"item": "TEST Notif Laptop", "quantity": 1, "asset_id": aid}],
        })
        assert hr.status_code == 200
        slip_no = hr.json()["slip_no"]

        # Baitulla session
        baitulla, _ = _login(*PR_EXEC)
        notes = baitulla.get(f"{API}/notifications").json()
        # Find notification matching this slip
        note = next((n for n in notes if n.get("slip_no") == slip_no), None)
        assert note is not None, f"Expected asset_receipt notification for {slip_no}"
        assert note["type"] == "asset_receipt"
        assert note["asset_id"] == aid

        # Test "pending" first: keeps status pending, stock NOT deducted
        rp = baitulla.post(f"{API}/notifications/{note['id']}/confirm", json={"action": "pending"})
        assert rp.status_code == 200
        assert rp.json()["stock_deducted"] is False
        # Asset still in_stock
        assert any(a["id"] == aid and a["status"] == "in_stock"
                   for a in admin["session"].get(f"{API}/assets?status=in_stock").json())

        # Confirm received - stock -1, asset assigned
        rc = baitulla.post(f"{API}/notifications/{note['id']}/confirm", json={"action": "received"})
        assert rc.status_code == 200, rc.text
        assert rc.json()["stock_deducted"] is True
        stock_after = admin["session"].get(f"{API}/assets?status=in_stock").json()
        assert not any(a["id"] == aid for a in stock_after), "asset must be removed from in_stock"
        # Assigned to Baitulla
        assigned = admin["session"].get(f"{API}/assets?assigned_to=Baitulla").json()
        assert any(a["id"] == aid and a["status"] == "assigned" for a in assigned)

    def test_notification_forbidden_for_other_user(self, admin, it_head):
        # Create handover to Baitulla, try to confirm as IT head -> 403
        sn = f"SN-{uuid.uuid4().hex[:8]}"
        admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST V4",
            "items": [{"product_name": "TEST N2", "quantity": 1, "rate": 100,
                       "assets": [{"serial_no": sn, "tag_id": f"T-{uuid.uuid4().hex[:6]}"}]}],
        })
        aid = next(a["id"] for a in admin["session"].get(f"{API}/assets?status=in_stock").json()
                   if a.get("serial_no") == sn)
        hr = admin["session"].post(f"{API}/handovers", json={
            "type": "handover", "employee_name": "Baitulla",
            "items": [{"item": "TEST N2", "quantity": 1, "asset_id": aid}],
        })
        slip_no = hr.json()["slip_no"]
        baitulla, _ = _login(*PR_EXEC)
        note = next(n for n in baitulla.get(f"{API}/notifications").json() if n.get("slip_no") == slip_no)
        # IT head is not owner, not super_admin
        rf = it_head["session"].post(f"{API}/notifications/{note['id']}/confirm", json={"action": "received"})
        assert rf.status_code == 403


class TestHandoverPDF:
    def test_handover_pdf_returns_pdf_bytes(self, admin):
        hr = admin["session"].post(f"{API}/handovers", json={
            "type": "handover", "employee_name": "TEST PDF Emp",
            "items": [{"item": "TEST PDF Item", "quantity": 1}],
            "prepared_by_sign": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
            "received_by_sign": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        })
        assert hr.status_code == 200
        hid = hr.json()["id"]
        r = admin["session"].get(f"{API}/handovers/{hid}/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_handover_pdf_requires_auth(self):
        # random id even; auth check fires first
        r = requests.get(f"{API}/handovers/000000000000000000000000/pdf")
        assert r.status_code == 401


class TestAssetsSummaryPDF:
    def test_summary_pdf_returns_pdf(self, admin):
        r = admin["session"].get(f"{API}/assets/summary/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_summary_pdf_requires_auth(self):
        r = requests.get(f"{API}/assets/summary/pdf")
        assert r.status_code == 401

    def test_handover_delete_requires_super_admin(self, pr_exec, admin):
        hr = admin["session"].post(f"{API}/handovers", json={
            "type": "handover", "employee_name": "TEST DelEmp",
            "items": [{"item": "TEST", "quantity": 1}],
        })
        hid = hr.json()["id"]
        # non-super
        rf = pr_exec["session"].delete(f"{API}/handovers/{hid}")
        assert rf.status_code == 403
        # super_admin ok
        rs = admin["session"].delete(f"{API}/handovers/{hid}")
        assert rs.status_code == 200


class TestDashboardStep2:
    def test_dashboard_has_assets_fields(self, admin):
        r = admin["session"].get(f"{API}/dashboard/stats")
        assert r.status_code == 200
        d = r.json()
        assert "assets_total" in d and isinstance(d["assets_total"], int)
        assert "assets_assigned" in d and isinstance(d["assets_assigned"], int)
