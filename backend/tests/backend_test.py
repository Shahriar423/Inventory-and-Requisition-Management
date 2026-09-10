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
        r = pr_exec["session"].post(f"{API}/requisitions", json={
            "requisition_type": "service",
            "items": [{"product_type": "consumable", "product_name": "TEST Reject", "quantity": 1, "rate": 100}],
        })
        rid = r.json()["id"]
        act = it_head["session"].post(f"{API}/requisitions/{rid}/action",
                                       json={"action": "reject", "note": "no"})
        assert act.status_code == 200
        assert act.json()["status"] == "rejected"


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
