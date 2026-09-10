# IMS — IT Requisition & Asset Management System

## Original Problem Statement
Build a production-ready IT Requisition & Asset Management System (originally specified as Laravel 11 + Inertia/React + MySQL). User agreed to build on the supported stack: **React + FastAPI + MongoDB**. Step 1: database architecture, models, dynamic role-based sidebar permissions, plus the working UI (Sidebar, Users & Roles, New Requisition form) matching the attached screenshots (dark navy + amber/cream enterprise theme).

## Architecture
- **Backend**: FastAPI (`/app/backend/server.py`), MongoDB via motor. All routes under `/api`.
- **Frontend**: React 19 + React Router + Tailwind + shadcn/ui. Amber/navy theme. Auth via httpOnly JWT cookies (axios `withCredentials`).
- **Auth**: email+password, bcrypt, JWT access(12h)+refresh(7d) cookies. RBAC via `require_roles`.

## User Personas / Roles
Super Admin, Dept Head, Executive, Accounts, MD (Managing Director), Purchase Head. Each user has `can_raise_pr` flag. Only Super Admin manages users/departments/categories/permissions.

## Core Requirements (static)
- Users & Roles CRUD with department + role + can_raise_pr.
- Departments & Categories (org hierarchy).
- Requisitions + items: auto Req No `REQ-YYYY-XXXX`, type Product/Service, product type Asset/Consumable, qty, rate, remarks, total, requester note, attachment (filename), status enum.
- Approval chains: **Product** → Dept Head → IT Head → Accounts → MD (if total ≥ 50,000 BDT) → Purchase Head. **Service** → IT Department Head directly.
- Dynamic sidebar permissions by role (`sidebar_permissions` collection, editable via Approver Management).

## Implemented (2026-09-10)
- JWT auth (login/logout/me/permissions), owner seeded as Super Admin (adolfhitlerrr64@gmail.com).
- Seed: 6 departments, 5 categories, 8 sample users (from screenshot) + owner.
- Dynamic role-filtered sidebar (7 groups / 15 items) matching nav screenshot.
- Users & Roles table with full CRUD + "Yes" PR badge.
- Departments & Categories CRUD.
- New Requisition multi-item form: live items table, total, rate-based MD threshold, Approval Priority visualizer (product/service), attachment + requester note, submit.
- Requisition lists: Pending / Approve (approver queue) / History / File Purchase (approved). Approve/Reject advances chain & recomputes status.
- Approver Management: per-role sidebar permission toggles.
- Dashboard stats + recent requisitions.
- **Verified**: 23/23 backend pytest + full frontend Playwright flows at 100%.

## Implemented — Step 2 (2026-09-10)
- **Service workflow**: statuses pending_it_service → product_collected_by_it → sent_to_service_center → service_completed_and_returned via `/api/requisitions/{id}/service-transition` (IT Head/super_admin). UI shows an "Advance" button for service reqs in the Approve queue.
- **Real file attachments**: Emergent object storage. `/api/files/upload` + `/api/files/{id}/download`. New Requisition form uploads attachments and stores the file id.
- **Purchase Requisition PDF**: reportlab-generated printable sheet matching the Primitek layout (item code, UoM, rate, totals, approver signature row); auto PR No `LPRIT-YYYYMM####`. "PDF" button on product requisitions.
- **Handover / Takeover**: `/api/handovers` with digital signature canvas (base64), Hand Over/Take Over slips (HO-/TO-####), item lines, remarks/notes. Handover assigns a linked asset to the employee; takeover returns it.
- **Stock GRN & asset tagging**: `/api/grns` captures vendor challan + per-unit serial/tag, creating tagged asset records (GRN-####). Stock List and Assigned Assets pages render assets and per-employee custody.
- Dashboard now includes asset counts. **Verified**: 34/34 backend tests + all Step 2 frontend flows at 100%.

## Backlog / Remaining (P1/P2)
- **P2 Router split**: server.py is large; split into modules before further growth.
- **P2 Handover guards**: validate asset is in_stock before assigning; match employee on takeover.
- **P2 Signed download tokens** instead of `?auth=` JWT query fallback.
- **P2 Approver Management** UI could also reorder/override approval chain approvers.
- **P2 Notifications** for pending approvals.
