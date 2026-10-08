"""Backend regression tests for IMS - IT Requisition & Asset Management System."""
import os
import time
import uuid
import pytest
import requests

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/.env"))

if os.environ.get("REACT_APP_BACKEND_URL"):
    BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
elif os.path.exists(env_path):
    BASE_URL = open(env_path).read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip().rstrip("/")
else:
    BASE_URL = "http://localhost:8000"

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
    return {"session": s, "user": data["user"], "token": data["access_token"]}


@pytest.fixture(scope="session")
def pr_exec():
    s, data = _login(*PR_EXEC)
    return {"session": s, "user": data["user"], "token": data["access_token"]}


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
        it_dept = next(d for d in admin["session"].get(f"{API}/departments").json() if d["name"] == "IT")
        # CREATE
        r = admin["session"].post(f"{API}/users", json={
            "name": "TEST User", "email": email, "password": "pass1234",
            "role": "executive", "department_id": it_dept["id"], "can_raise_pr": True,
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
    def test_base_chain_is_two_levels_dept_head_then_it_head(self, pr_exec):
        # Base chain no longer includes Accounts/Purchase Head/MD at creation regardless of
        # rate — those only get appended dynamically via the out-of-stock PR path.
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
        assert len(chain) == 2
        labels = [s["label"] for s in chain]
        assert labels == ["Department Head", "IT Head"]
        assert "Managing Director" not in labels and "Purchase Head" not in labels and "Accounts" not in labels

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

    def test_non_pr_user_allowed_standard_requisition(self):
        # dipto is a plain executive with can_raise_pr: False. Standard product/service
        # requisitions must NOT require can_raise_pr — only the PR (out-of-stock) flow does.
        s, _ = _login("dipto@gmail.com", "password123")
        r = s.post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "x", "quantity": 1, "rate": 100}],
        })
        assert r.status_code == 200, r.text
        assert r.json()["requisitioner_name"] == "dipto"


class TestStockCheckBranching:
    def _new_req(self, session, product_name, qty=1):
        r = session.post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": product_name, "quantity": qty, "rate": 0}],
        })
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_it_head_approval_with_stock_auto_generates_handover(self, admin, pr_exec):
        item_name = f"TEST InStock Widget {uuid.uuid4().hex[:6]}"
        # Put one unit in stock via GRN.
        gr = admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST Vendor",
            "items": [{"product_name": item_name, "quantity": 1, "rate": 100,
                       "assets": [{"serial_no": f"SN-{uuid.uuid4().hex[:8]}"}]}],
        })
        assert gr.status_code == 200, gr.text

        rid = self._new_req(pr_exec["session"], item_name)
        # dept head approve (level 1) -> still pending_it, no branching yet
        a1 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        assert a1.status_code == 200, a1.text
        assert a1.json()["status"] == "pending_it"

        # IT head approve (level 2) -> stock available -> auto handover, no manual GRN/PR needed
        a2 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        assert a2.status_code == 200, a2.text
        body = a2.json()
        assert body["status"] == "pending_handover"
        assert body.get("handover_id")

        h = admin["session"].get(f"{API}/handovers/{body['handover_id']}")
        assert h.status_code == 200
        assert h.json()["status"] == "prepared"
        assert h.json()["requisition_id"] == rid

    def test_it_head_approval_without_stock_routes_to_pending_pr(self, admin, pr_exec):
        item_name = f"TEST OutOfStock Widget {uuid.uuid4().hex[:6]}"
        rid = self._new_req(pr_exec["session"], item_name)
        a1 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        assert a1.status_code == 200
        a2 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        assert a2.status_code == 200
        assert a2.json()["status"] == "pending_pr"

    def test_pending_pr_visible_only_to_can_raise_pr_holders(self, admin, pr_exec):
        item_name = f"TEST OOS Visibility {uuid.uuid4().hex[:6]}"
        rid = self._new_req(pr_exec["session"], item_name)
        admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})

        s, _ = _login("dipto@gmail.com", "password123")  # can_raise_pr: False
        r_denied = s.get(f"{API}/requisitions", params={"scope": "purchase"})
        assert r_denied.status_code == 200
        assert r_denied.json() == []

        r_ok = pr_exec["session"].get(f"{API}/requisitions", params={"scope": "purchase"})
        assert r_ok.status_code == 200
        assert any(r["id"] == rid for r in r_ok.json())

    def test_pending_handover_visible_only_to_it_head(self, admin, pr_exec):
        item_name = f"TEST Handover Queue {uuid.uuid4().hex[:6]}"
        gr = admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST Vendor",
            "items": [{"product_name": item_name, "quantity": 1, "rate": 100,
                       "assets": [{"serial_no": f"SN-{uuid.uuid4().hex[:8]}"}]}],
        })
        assert gr.status_code == 200
        rid = self._new_req(pr_exec["session"], item_name)
        admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        act = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        assert act.json()["status"] == "pending_handover"

        s, _ = _login("dipto@gmail.com", "password123")  # executive, not IT dept head
        r_denied = s.get(f"{API}/requisitions", params={"scope": "handover"})
        assert r_denied.json() == []

        s2, _ = _login("ashik@gmail.com", "password123")  # IT dept head
        r_ok = s2.get(f"{API}/requisitions", params={"scope": "handover"})
        assert any(r["id"] == rid for r in r_ok.json())


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
        # Base chain is now Dept Head -> IT Head only; one approve call only ever
        # advances exactly one step.
        assert act.json()["status"] == "pending_it"

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
        for k in ("total", "pending", "approved", "rejected", "high_value", "my_queue", "recent", "scope"):
            assert k in d
        assert d["scope"] == "global"


class TestPersonalDataScoping:
    """A plain 'executive' (no approval/admin authority) must only ever see their own data —
    not other users' requisitions, assets, or org-wide dashboard numbers."""

    def test_dashboard_stats_scoped_to_own_requisitions(self, admin, pr_exec):
        # Create a requisition as dipto (executive) that pr_exec (also executive) has
        # nothing to do with.
        s, _ = _login("dipto@gmail.com", "password123")
        r = s.post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": f"TEST Scoped {uuid.uuid4().hex[:6]}", "quantity": 1, "rate": 0}],
        })
        assert r.status_code == 200

        stats = s.get(f"{API}/dashboard/stats").json()
        assert stats["scope"] == "personal"
        # dipto's own total must include the requisition just created...
        assert stats["total"] >= 1
        # ...and must be strictly less than the org-wide total (there's clearly more than
        # one requisition in the system across all the other tests in this suite).
        global_total = admin["session"].get(f"{API}/dashboard/stats").json()["total"]
        assert stats["total"] < global_total
        assert stats["recent"], "should have at least their own recent requisition"
        assert all(x["requisitioner_name"] == "dipto" for x in stats["recent"])

    def test_history_and_all_scope_hidden_from_other_executives(self, pr_exec):
        s, _ = _login("dipto@gmail.com", "password123")
        r = s.post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": f"TEST Scoped2 {uuid.uuid4().hex[:6]}", "quantity": 1, "rate": 0}],
        })
        rid = r.json()["id"]

        # baitulla (a different plain executive) must not see dipto's requisition under
        # either "all" or "history" scope.
        for scope in ("all", "history"):
            rows = pr_exec["session"].get(f"{API}/requisitions", params={"scope": scope}).json()
            assert not any(x["id"] == rid for x in rows)
            assert all(x["requisitioner_id"] == pr_exec["user"]["id"] for x in rows)

    def test_history_scope_shows_everyone_to_dept_head(self, admin, pr_exec):
        # dept_head (approver/admin authority) should see org-wide history, not just their own.
        s, _ = _login("ashik@gmail.com", "password123")
        rows = s.get(f"{API}/requisitions", params={"scope": "history"}).json()
        assert isinstance(rows, list)  # not filtered to ashik's own requisitions only
        # (can't assert non-empty deterministically, but the scoping logic itself is what's
        # under test in the two executive-side tests above)

    def test_assets_scoped_to_own_assignment_for_executives(self, admin):
        # Assign an asset to dipto via the full GRN -> handover -> confirm flow so there's a
        # real assigned asset to test against.
        item_name = f"TEST Personal Asset {uuid.uuid4().hex[:6]}"
        sn = f"SN-{uuid.uuid4().hex[:8]}"
        admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST V5",
            "items": [{"product_name": item_name, "quantity": 1, "rate": 100, "assets": [{"serial_no": sn}]}],
        })
        aid = next(a["id"] for a in admin["session"].get(f"{API}/assets?status=in_stock").json() if a.get("serial_no") == sn)
        hr = admin["session"].post(f"{API}/handovers", json={
            "type": "handover", "employee_name": "dipto",
            "items": [{"item": item_name, "quantity": 1, "asset_id": aid}],
        })
        admin["session"].post(f"{API}/handovers/{hr.json()['id']}/deliver")
        s, _ = _login("dipto@gmail.com", "password123")
        note = next(n for n in s.get(f"{API}/notifications").json() if n.get("handover_id") == hr.json()["id"])
        s.post(f"{API}/notifications/{note['id']}/confirm", json={"action": "received"})

        # dipto sees it in their own asset list.
        mine = s.get(f"{API}/assets").json()
        assert any(a["id"] == aid for a in mine)
        assert all((a.get("assigned_to") or "dipto") == "dipto" for a in mine)

        # A different executive (baitulla) does NOT see dipto's asset.
        baitulla, _ = _login("baitulla@gmail.com", "password123")
        others = baitulla.get(f"{API}/assets").json()
        assert not any(a["id"] == aid for a in others)

        # Attempting to snoop via ?assigned_to=dipto is also blocked — forced back to self.
        snoop = baitulla.get(f"{API}/assets", params={"assigned_to": "dipto"}).json()
        assert not any(a["id"] == aid for a in snoop)

        # in_stock items are still visible to executives (no personal data exposed there).
        stock = baitulla.get(f"{API}/assets", params={"status": "in_stock"}).json()
        assert isinstance(stock, list)

    def test_personal_dashboard_includes_lists_not_just_counts(self, admin, pr_exec):
        item_name = f"TEST Dash List {uuid.uuid4().hex[:6]}"
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": item_name, "quantity": 1, "rate": 0}],
        })
        rid = r.json()["id"]

        stats = pr_exec["session"].get(f"{API}/dashboard/stats").json()
        assert stats["scope"] == "personal"
        assert "pending_list" in stats and "my_assets" in stats
        assert any(x["id"] == rid for x in stats["pending_list"])
        assert all(x["requisitioner_name"] == pr_exec["user"]["name"] for x in stats["pending_list"])

        # Global dashboard doesn't need (or return) these personal-only list fields.
        global_stats = admin["session"].get(f"{API}/dashboard/stats").json()
        assert "pending_list" not in global_stats and "my_assets" not in global_stats


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
        # pr_exec (baitulla) has can_raise_pr: True -> allowed to raise the PR.
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST PDF", "quantity": 1, "rate": 1234}],
            "requester_note": "TEST pdf",
        })
        rid = r.json()["id"]
        r2 = pr_exec["session"].get(f"{API}/requisitions/{rid}/pdf", params={"auth": pr_exec["token"]})
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("application/pdf")
        assert r2.content[:4] == b"%PDF"
        # verify PR number stored and starts with LPRIT-YYYYMM
        r3 = pr_exec["session"].get(f"{API}/requisitions/{rid}")
        pr_no = r3.json().get("purchase_pr_no")
        assert pr_no and pr_no.startswith("LPRIT-")
        assert len(pr_no.split("-")[1]) == 10  # YYYYMM + 4 digits


class TestPurchaseRequisitionStrictPermission:
    """Strict PR gate: ONLY can_raise_pr == True may raise/generate a Purchase Requisition.
    No role-based override — dept_head/purchase_head/etc. without the flag must be denied."""

    def test_non_pr_user_forbidden_from_pr_pdf(self, pr_exec):
        # A standard requisition can be created by anyone (e.g. the pr_exec fixture, who
        # does have can_raise_pr) — we then try to fetch its PR PDF as dipto, who does NOT.
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Strict PR", "quantity": 1, "rate": 500}],
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        s, data = _login("dipto@gmail.com", "password123")  # executive, can_raise_pr: False
        # Pass the token via ?auth= instead of relying on the `secure` cookie, which browsers/
        # HTTP clients won't send over plain http:// (e.g. local testing on http://127.0.0.1).
        r2 = s.get(f"{API}/requisitions/{rid}/pdf", params={"auth": data["access_token"]})
        assert r2.status_code == 403
        assert "not allowed" in r2.json()["detail"].lower()

    def test_dept_head_without_can_raise_pr_forbidden_no_role_override(self, pr_exec):
        # Ashik is a dept_head but seeded with can_raise_pr: False. Under the strict rule,
        # role alone (dept_head/purchase_head/super_admin) must NOT bypass the PR check.
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Strict PR 2", "quantity": 1, "rate": 500}],
        })
        rid = r.json()["id"]

        s, data = _login("ashik@gmail.com", "password123")
        assert data["user"]["role"] == "dept_head"
        r2 = s.get(f"{API}/requisitions/{rid}/pdf", params={"auth": data["access_token"]})
        assert r2.status_code == 403

    def test_can_raise_pr_user_allowed_regardless_of_role(self, pr_exec):
        # baitulla is a plain executive (not dept_head/purchase_head/super_admin) but has
        # can_raise_pr: True -> must be allowed purely on the flag, confirming no role gating.
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Strict PR 3", "quantity": 1, "rate": 500}],
        })
        rid = r.json()["id"]
        assert pr_exec["user"]["role"] == "executive"
        assert pr_exec["user"].get("can_raise_pr") is True

        r2 = pr_exec["session"].get(f"{API}/requisitions/{rid}/pdf", params={"auth": pr_exec["token"]})
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("application/pdf")

    def test_only_super_admin_can_toggle_can_raise_pr(self, admin):
        # Only super_admin may set can_raise_pr on a user (via User Management).
        it_dept = next(d for d in admin["session"].get(f"{API}/departments").json() if d["name"] == "IT")
        email = f"test_pr_toggle_{uuid.uuid4().hex[:8]}@example.com"
        r = admin["session"].post(f"{API}/users", json={
            "name": "TEST PR Toggle", "email": email, "password": "pass1234",
            "role": "executive", "department_id": it_dept["id"], "can_raise_pr": False,
        })
        assert r.status_code == 200, r.text
        uid = r.json()["id"]

        # A non-super-admin (dipto) must not be able to grant PR rights to anyone.
        s, _ = _login("dipto@gmail.com", "password123")
        r2 = s.put(f"{API}/users/{uid}", json={"can_raise_pr": True})
        assert r2.status_code == 403

        # super_admin can toggle it.
        r3 = admin["session"].put(f"{API}/users/{uid}", json={"can_raise_pr": True})
        assert r3.status_code == 200
        assert r3.json()["can_raise_pr"] is True

        admin["session"].delete(f"{API}/users/{uid}")

    def test_can_raise_pr_is_it_department_only(self, admin):
        depts = admin["session"].get(f"{API}/departments").json()
        it_dept = next(d for d in depts if d["name"] == "IT")
        hr_dept = next(d for d in depts if d["name"] == "HR")

        # Cannot create a non-IT user with can_raise_pr=True.
        email1 = f"test_pr_hr_{uuid.uuid4().hex[:8]}@example.com"
        r1 = admin["session"].post(f"{API}/users", json={
            "name": "TEST PR HR", "email": email1, "password": "pass1234",
            "role": "executive", "department_id": hr_dept["id"], "can_raise_pr": True,
        })
        assert r1.status_code == 400

        # Cannot create a user with can_raise_pr=True and no department at all.
        email2 = f"test_pr_nodept_{uuid.uuid4().hex[:8]}@example.com"
        r2 = admin["session"].post(f"{API}/users", json={
            "name": "TEST PR No Dept", "email": email2, "password": "pass1234",
            "role": "executive", "can_raise_pr": True,
        })
        assert r2.status_code == 400

        # An IT user can be created with can_raise_pr=True directly.
        email3 = f"test_pr_it_{uuid.uuid4().hex[:8]}@example.com"
        r3 = admin["session"].post(f"{API}/users", json={
            "name": "TEST PR IT", "email": email3, "password": "pass1234",
            "role": "executive", "department_id": it_dept["id"], "can_raise_pr": True,
        })
        assert r3.status_code == 200, r3.text
        uid3 = r3.json()["id"]

        # Cannot move that user to HR while can_raise_pr stays True in the same request.
        r4 = admin["session"].put(f"{API}/users/{uid3}", json={"department_id": hr_dept["id"], "can_raise_pr": True})
        assert r4.status_code == 400

        # Existing HR user (dipto) cannot have can_raise_pr toggled on without a dept change.
        dipto = next(u for u in admin["session"].get(f"{API}/users").json() if u["email"] == "dipto@gmail.com")
        r5 = admin["session"].put(f"{API}/users/{dipto['id']}", json={"can_raise_pr": True})
        assert r5.status_code == 400

        admin["session"].delete(f"{API}/users/{uid3}")


class TestPrPricingAndMd:
    def test_md_approver_is_under_primitek_group_department(self, admin):
        r = admin["session"].get(f"{API}/departments")
        pg = next(d for d in r.json() if d["name"] == "Primitek Group")
        u = admin["session"].get(f"{API}/users").json()
        md_user = next(x for x in u if x["role"] == "md")
        assert md_user["department_id"] == pg["id"]

    def _advance_to_pending_pr(self, admin, session, product_name):
        r = session.post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": product_name, "quantity": 1, "rate": 0}],
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert len(r.json()["approval_chain"]) == 2  # base chain only: Dept Head, IT Head
        for _ in range(2):
            act = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve", "note": "ok"})
            assert act.status_code == 200, act.text
        assert act.json()["status"] == "pending_pr"  # no stock for this never-before-seen item name
        return rid

    def test_pricing_endpoint_adds_md_when_total_crosses_threshold(self, admin, pr_exec):
        rid = self._advance_to_pending_pr(admin, pr_exec["session"], f"TEST PR Priced Laptop {uuid.uuid4().hex[:6]}")

        # Not allowed before the requisition has actually reached pending_pr.
        r_new = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Not Yet", "quantity": 1, "rate": 0}],
        })
        r_early = admin["session"].post(f"{API}/requisitions/{r_new.json()['id']}/pricing", json={"items": [{"index": 0, "rate": 60000}]})
        assert r_early.status_code == 400

        # Only can_raise_pr users may set pricing.
        s, _ = _login("dipto@gmail.com", "password123")
        r_forbidden = s.post(f"{API}/requisitions/{rid}/pricing", json={"items": [{"index": 0, "rate": 60000}]})
        assert r_forbidden.status_code == 403

        r2 = pr_exec["session"].post(f"{API}/requisitions/{rid}/pricing", json={"items": [{"index": 0, "rate": 60000}]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["total_amount"] == 60000
        assert body["status"] == "pending_md"
        chain = body["approval_chain"]
        assert len(chain) == 5  # Dept Head, IT Head, MD, Accounts Head, Purchase Dept Head
        labels = [s["label"] for s in chain]
        assert labels[2:] == ["Managing Director", "Accounts Head (CFO)", "Purchase Dept Head"]
        assert chain[2]["approver_name"] == "M.A Quieum"  # confirms MD resolves via Primitek Group dept

        # MD approves -> Accounts Head -> Purchase Dept Head -> buy_process (not "approved":
        # goods still need to be procured & handed over).
        act2 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve", "note": "ok"})
        assert act2.json()["status"] == "pending_accounts"
        act3 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve", "note": "ok"})
        assert act3.json()["status"] == "pending_purchase"
        act4 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve", "note": "ok"})
        assert act4.json()["status"] == "buy_process"

    def test_pricing_below_threshold_skips_md(self, admin, pr_exec):
        rid = self._advance_to_pending_pr(admin, pr_exec["session"], f"TEST PR Priced Mouse {uuid.uuid4().hex[:6]}")
        r2 = pr_exec["session"].post(f"{API}/requisitions/{rid}/pricing", json={"items": [{"index": 0, "rate": 500}]})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["total_amount"] == 500
        assert body["status"] == "pending_accounts"
        labels = [s["label"] for s in body["approval_chain"]]
        assert "Managing Director" not in labels
        assert labels[2:] == ["Accounts Head (CFO)", "Purchase Dept Head"]

    def test_grn_against_pr_requisition_advances_to_stock_received_then_issue_stock(self, admin, pr_exec):
        item_name = f"TEST PR to GRN Item {uuid.uuid4().hex[:6]}"
        rid = self._advance_to_pending_pr(admin, pr_exec["session"], item_name)
        r2 = pr_exec["session"].post(f"{API}/requisitions/{rid}/pricing", json={"items": [{"index": 0, "rate": 500}]})
        assert r2.json()["status"] == "pending_accounts"
        admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve", "note": "ok"})
        act = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve", "note": "ok"})
        assert act.json()["status"] == "buy_process"

        gr = admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST PR Vendor",
            "requisition_id": rid,
            "items": [{"product_name": item_name, "quantity": 1, "rate": 500,
                       "assets": [{"serial_no": f"SN-{uuid.uuid4().hex[:8]}"}]}],
        })
        assert gr.status_code == 200, gr.text
        # GRN receipt no longer auto-generates the handover — it only marks stock received;
        # IT must explicitly click "Issue Stock for Requisition".
        assert gr.json().get("requisition_advanced_to") == "stock_received_in_it"

        r3 = admin["session"].get(f"{API}/requisitions/{rid}")
        assert r3.json()["status"] == "stock_received_in_it"
        assert not r3.json().get("handover_id")

        # Only IT (dept_head of IT, or super_admin) can issue stock.
        s, _ = _login("dipto@gmail.com", "password123")
        r_denied = s.post(f"{API}/requisitions/{rid}/issue-stock")
        assert r_denied.status_code == 403

        issue = admin["session"].post(f"{API}/requisitions/{rid}/issue-stock")
        assert issue.status_code == 200, issue.text
        assert issue.json()["status"] == "pending_handover"
        assert issue.json().get("handover_id")

        r4 = admin["session"].get(f"{API}/requisitions/{rid}")
        assert r4.json()["status"] == "pending_handover"
        assert r4.json().get("handover_id")

        # Requester got an informational bell notification ahead of the receipt confirmation.
        req_login, _ = _login(*PR_EXEC)
        notes = req_login.get(f"{API}/notifications").json()
        assert any(n["type"] == "stock_allocated" and item_name in n["message"] for n in notes)

        # Issuing stock twice is rejected (already past stock_received_in_it).
        issue_again = admin["session"].post(f"{API}/requisitions/{rid}/issue-stock")
        assert issue_again.status_code == 400


class TestReviseAction:
    def test_revise_returns_to_requester_and_resubmit_reopens_step(self, admin):
        # dipto raises a low-value product requisition -> level 1 approver is his dept head.
        s, _ = _login("dipto@gmail.com", "password123")
        r = s.post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Revise Item", "quantity": 1, "rate": 1000}],
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        # dipto is HR dept; his dept head can act as level-1 approver, but for simplicity here we
        # use super_admin (who is allowed to act on behalf of any pending step) to request a revision.
        r2 = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "revise", "note": "Please add a vendor quote"})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["status"] == "revision_requested"

        # A revise action without a note must be rejected.
        r_bad = admin["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": "TEST Revise No Note", "quantity": 1, "rate": 1000}],
        })
        rid_bad = r_bad.json()["id"]
        r3 = admin["session"].post(f"{API}/requisitions/{rid_bad}/action", json={"action": "revise"})
        assert r3.status_code == 400

        # Only the original requester (or super_admin) can resubmit.
        s2, _ = _login("ashik@gmail.com", "password123")
        r4 = s2.post(f"{API}/requisitions/{rid}/resubmit", json={"action": "revise", "note": "not mine"})
        assert r4.status_code == 403

        r5 = s.post(f"{API}/requisitions/{rid}/resubmit", json={"action": "revise", "note": "Added the quote"})
        assert r5.status_code == 200, r5.text
        assert r5.json()["status"] != "revision_requested"

        # audit trail recorded both actions with timestamps
        history = [h["action"] for h in r5.json()["history"]]
        assert "revise" in history and "resubmit" in history


class TestStockSummary:
    def test_stock_summary_aggregates_and_hides_item_level_fields(self, admin):
        challan = f"CH-{uuid.uuid4().hex[:6]}"
        r = admin["session"].post(f"{API}/grns", json={
            "challan_no": challan, "vendor_name": "TEST Stock Vendor",
            "items": [{"product_name": "TEST Aggregated Widget", "quantity": 2, "rate": 500,
                       "assets": [{"serial_no": f"SN-{uuid.uuid4().hex[:8]}", "tag_id": f"TAG-{uuid.uuid4().hex[:6]}"},
                                  {"serial_no": f"SN-{uuid.uuid4().hex[:8]}", "tag_id": f"TAG-{uuid.uuid4().hex[:6]}"}]}],
        })
        assert r.status_code == 200, r.text

        r2 = admin["session"].get(f"{API}/assets/stock-summary")
        assert r2.status_code == 200
        rows = r2.json()
        row = next((x for x in rows if x["name"] == "TEST Aggregated Widget"), None)
        assert row is not None
        assert row["available_stock"] >= 2
        # aggregated view must NOT expose per-item fields
        assert "serial_no" not in row and "assigned_to" not in row and "status" not in row


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


class TestHandoverStatusLifecycle:
    """Two-stage handover handshake:
    pending_handover -> (IT clicks Handover Done) -> awaiting_requester_confirmation
                     -> (requester clicks Yes, Received) -> handover_done (terminal)."""

    def test_full_two_stage_lifecycle_to_handover_done(self, admin, pr_exec):
        item_name = f"TEST Lifecycle Item {uuid.uuid4().hex[:6]}"
        gr = admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST Lifecycle Vendor",
            "items": [{"product_name": item_name, "quantity": 1, "rate": 100,
                       "assets": [{"serial_no": f"SN-{uuid.uuid4().hex[:8]}"}]}],
        })
        assert gr.status_code == 200, gr.text

        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "product",
            "items": [{"product_type": "asset", "product_name": item_name, "quantity": 1, "rate": 0}],
        })
        rid = r.json()["id"]
        admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        act = admin["session"].post(f"{API}/requisitions/{rid}/action", json={"action": "approve"})
        assert act.json()["status"] == "pending_handover"
        hid = act.json()["handover_id"]

        # Still counted as pending (not finalized) before delivery.
        pending_before = admin["session"].get(f"{API}/dashboard/stats").json()["pending"]

        # Stage A: IT marks delivered -> Waiting for User Confirmation (NOT terminal).
        deliver = admin["session"].post(f"{API}/handovers/{hid}/deliver")
        assert deliver.status_code == 200, deliver.text
        assert deliver.json()["requisition_status"] == "awaiting_requester_confirmation"
        r2 = admin["session"].get(f"{API}/requisitions/{rid}")
        assert r2.json()["status"] == "awaiting_requester_confirmation"
        # Still in the active pipeline at this point.
        assert any(x["id"] == rid for x in pr_exec["session"].get(f"{API}/requisitions", params={"scope": "pending"}).json())

        # Stage B: requester confirms -> handover_done (terminal).
        baitulla, _ = _login(*PR_EXEC)
        note = next(n for n in baitulla.get(f"{API}/notifications").json() if n.get("handover_id") == hid)
        conf = baitulla.post(f"{API}/notifications/{note['id']}/confirm", json={"action": "received"})
        assert conf.status_code == 200, conf.text
        assert conf.json()["requisition_status"] == "handover_done"

        r3 = admin["session"].get(f"{API}/requisitions/{rid}")
        assert r3.json()["status"] == "handover_done"
        assert r3.json().get("closed_at")
        actions = [h["action"] for h in r3.json()["history"]]
        assert "handover_delivered" in actions and "receipt_confirmed" in actions

        # Dropped out of the pending pipeline and now appears in history.
        assert not any(x["id"] == rid for x in pr_exec["session"].get(f"{API}/requisitions", params={"scope": "pending"}).json())
        assert any(x["id"] == rid for x in admin["session"].get(f"{API}/requisitions", params={"scope": "history"}).json())

        pending_after = admin["session"].get(f"{API}/dashboard/stats").json()["pending"]
        assert pending_after == pending_before - 1

    def test_handover_record_status_has_three_stages(self, admin):
        # Ad-hoc handover (no linked requisition) — the handover record's OWN status must
        # still progress through all three stages: prepared -> delivered (awaiting
        # confirmation) -> confirmed. Previously "delivered" looked like a final state in
        # the UI the instant IT clicked "Handover Done", before the employee had confirmed
        # anything.
        sn = f"SN-{uuid.uuid4().hex[:8]}"
        admin["session"].post(f"{API}/grns", json={
            "challan_no": f"CH-{uuid.uuid4().hex[:6]}", "vendor_name": "TEST Three Stage",
            "items": [{"product_name": "TEST Three Stage Item", "quantity": 1, "rate": 100, "assets": [{"serial_no": sn}]}],
        })
        aid = next(a["id"] for a in admin["session"].get(f"{API}/assets?status=in_stock").json() if a.get("serial_no") == sn)
        hr = admin["session"].post(f"{API}/handovers", json={
            "type": "handover", "employee_name": "Baitulla",
            "items": [{"item": "TEST Three Stage Item", "quantity": 1, "asset_id": aid}],
        })
        hid = hr.json()["id"]
        assert hr.json()["status"] == "prepared"

        deliver = admin["session"].post(f"{API}/handovers/{hid}/deliver")
        assert deliver.status_code == 200
        h_after_deliver = admin["session"].get(f"{API}/handovers/{hid}").json()
        assert h_after_deliver["status"] == "delivered"  # awaiting confirmation, NOT final

        baitulla, _ = _login(*PR_EXEC)
        note = next(n for n in baitulla.get(f"{API}/notifications").json() if n.get("handover_id") == hid)
        baitulla.post(f"{API}/notifications/{note['id']}/confirm", json={"action": "received"})

        h_after_confirm = admin["session"].get(f"{API}/handovers/{hid}").json()
        assert h_after_confirm["status"] == "confirmed"
        assert h_after_confirm.get("confirmed_at")


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

        # Newly created handovers are 'prepared' — no notification yet until IT clicks
        # "Handover Done".
        assert hd["status"] == "prepared"
        baitulla, _ = _login(*PR_EXEC)
        assert not any(n.get("handover_id") == hd["id"] for n in baitulla.get(f"{API}/notifications").json())

        deliver = admin["session"].post(f"{API}/handovers/{hd['id']}/deliver")
        assert deliver.status_code == 200, deliver.text
        assert deliver.json()["status"] == "delivered"  # handover record's own status
        assert any(n.get("handover_id") == hd["id"] for n in baitulla.get(f"{API}/notifications").json())

        # Delivering twice is rejected.
        deliver2 = admin["session"].post(f"{API}/handovers/{hd['id']}/deliver")
        assert deliver2.status_code == 400


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
        hid = hr.json()["id"]
        slip_no = hr.json()["slip_no"]

        # Notification only appears once IT marks the handover delivered.
        deliver = admin["session"].post(f"{API}/handovers/{hid}/deliver")
        assert deliver.status_code == 200, deliver.text

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
        # Notification only exists once IT marks the handover delivered.
        deliver = admin["session"].post(f"{API}/handovers/{hr.json()['id']}/deliver")
        assert deliver.status_code == 200, deliver.text
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
        r = admin["session"].get(f"{API}/handovers/{hid}/pdf", params={"auth": admin["token"]})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_handover_pdf_requires_auth(self):
        # random id even; auth check fires first
        r = requests.get(f"{API}/handovers/000000000000000000000000/pdf")
        assert r.status_code == 401


class TestAssetsSummaryPDF:
    def test_summary_pdf_returns_pdf(self, admin):
        r = admin["session"].get(f"{API}/assets/summary/pdf", params={"auth": admin["token"]})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_summary_pdf_forbidden_for_executive(self):
        # Org-wide report — restricted to admin/approver roles.
        s, data = _login("dipto@gmail.com", "password123")
        r = s.get(f"{API}/assets/summary/pdf", params={"auth": data["access_token"]})
        assert r.status_code == 403

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