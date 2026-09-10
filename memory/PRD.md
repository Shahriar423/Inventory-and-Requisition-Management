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

## Backlog / Remaining (P1/P2)
- **P1 Assigned Assets**: track assets assigned to employees (screenshot: Handover/Take Over forms).
- **P1 Handover Module & Records**: hand-over / take-over slips (per attached Primitek handover sheet).
- **P1 File Purchase Requisition (PR document)**: generate the printable Purchase Requisition (LPRIT-YYYY...) with item code, UoM, last purchase history, signatures.
- **P2 Stock List & Stock GRN (Vendor Challan)**.
- **P2 Real file/object storage** for attachments (currently filename-only).
- **P2 Notifications** for pending approvals; brute-force lockout hardening.
- **P2 Service workflow extra statuses** (product_collected_by_it, sent_to_service_center) as manual IT transitions.

## Next Tasks
1. Assigned Assets module + Handover/Take-over records.
2. Printable Purchase Requisition document generation.
3. Object storage for attachments.
