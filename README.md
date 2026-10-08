# IRM - IT Requisition & Asset Management System

A web application for requesting, approving, purchasing, storing, handing over and tracking IT and office assets, plus an IT service-desk queue for support tickets.

Employees raise a requisition, the right managers approve it, and the system either issues the item from stock or sends it through a Purchase Requisition (PR) and Purchase Order (PO) process. IT then hands the item over, the employee confirms receipt with a signature, and the asset is recorded against that person for its whole life.

> A non-technical walkthrough of every screen and workflow is in [`docs/IRM_Project_Report.pdf`](docs/IRM_Project_Report.pdf).

<p align="center">
  <img src="docs/dashboard.png" alt="Department overview dashboard" width="760"><br>
  <sub>Department overview (live counters and the IT Service Queue)</sub>
</p>

---

## Table of contents

- [Features](#features)
- [How a request flows](#how-a-request-flows)
- [Roles and permissions](#roles-and-permissions)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [First-time setup inside the app](#first-time-setup-inside-the-app)
- [Useful scripts](#useful-scripts)
- [Security notes](#security-notes)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

---

## Features

| Area | What it does |
|---|---|
| **Requisitions** | Raise product requests (IT Asset, IT Accessories, Network, Consumable, Furniture) or IT service requests. Edit and resubmit when an approver asks for changes. |
| **Approval chains** | Automatic approver lookup by department, with smart bypasses (for example the requester is already the Department Head), approve / reject / revise, full history. |
| **Stock** | Live available-stock list; every unit tracked by serial number and tag with status (in stock, reserved, assigned). |
| **Purchasing** | Purchase Requisition (PR) filed by the PR Handler, IT Head review, then Purchase Order (PO) with amount-based routing: Purchase Head, MD, Accounts Head. Limits are configurable. |
| **Goods receiving (GRN)** | Record vendor deliveries by challan, tag each device, and link the delivery to the requisition it fulfils. |
| **Handover** | Handover, takeover (return) and swap slips with printable PDFs, reservation of units, and employee receipt confirmation with an on-screen signature. |
| **IT service desk** | Ticket queues for the Application and Network and Infra teams: claim, release, complete, or request an external repair that the IT Head approves. |
| **Notifications and reminders** | In-app bell; automatic reminder to an approver after 24 hours (configurable); leave delegation to a colleague for a date range. |
| **Audit** | Search any requisition or PR number and open a Master Audit PDF with the full trail. Per-asset life history. |
| **Administration** | Departments, categories, product catalogue, users and roles, per-role menu access, department-scoped permission switches. |
| **Passwords** | Self-service change password; admin-assisted reset that issues a one-time temporary password and forces a change at next login. |
| **Bulk import** | Super Admin only: load employees and the assets they already hold from an Excel or CSV template, with a dry-run preview and row-by-row error report. |
| **PDFs** | Purchase Requisition, Handover slip, Assets summary, Master Audit report. |

## How a request flows

```
Employee raises requisition
        |
Department Head approves
        |
   Stock check
   |-- In stock  --> IT Head approves stock issue --> handover slip is prepared
   |
   '-- Not in stock --> PR Handler files PR --> IT Head reviews PR
                          --> PO created and approved
                              (<= limit: Purchase Head | > limit: MD, then Accounts Head)
                          --> goods bought --> received in IT (GRN) --> IT issues stock
        |
IT hands over --> employee confirms and signs --> asset recorded as "assigned"
```

Consumables and furniture take a shorter **Admin track** (Admin Head approval only, then handover or "waiting for stock").
IT service requests skip manager approval and go straight to the right IT team queue.

## Roles and permissions

| Role | Typical responsibilities |
|---|---|
| **Executive** | Raises requisitions, confirms receipt of devices. IT executives also work service tickets. |
| **Department Head** | Approves their department's requests. The **IT Head** also approves stock issues, PR reviews and repairs, runs handover, and uses audit search. |
| **Purchase Head** | Approves POs, receives stock (GRN), can create POs. |
| **Accounts Head** | Approves larger POs, views stock. |
| **MD** | Approves POs above the MD limit; company-wide visibility. |
| **Super Admin** | Manages departments, users, products and menus; resets passwords; bulk import; can act on any step. |

Extra per-person switches: **Can Raise PR** (IT department only), **Can Create PO** (Purchase department only), and an **IT team** (Application or Network and Infra).
Menus are enforced both in the UI and on the server. Data visibility is three-level: personal (executives), department (heads), company-wide (Super Admin, MD).

## Tech stack

**Frontend**
- React 19 (Create React App with CRACO), React Router 7
- Tailwind CSS, Radix UI / shadcn components, Lucide icons, Sonner toasts, Recharts
- Axios for API calls

**Backend**
- Python 3 and FastAPI, served with Uvicorn
- MongoDB with Motor (async driver)
- JWT sign-in (cookie plus bearer header), bcrypt password hashing
- ReportLab (PDFs), openpyxl (Excel import/templates)

## Project structure

```
.
├── backend/
│   ├── server.py                 # FastAPI app: all API routes, business rules, PDFs, bulk import
│   ├── create_super_admin.py     # First-run script: base departments + first Super Admin
│   ├── clear_db.py               # Dev helper: wipes sample transactional data (use with care)
│   ├── fix_orphaned_handovers.py # One-off data repair script
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/                # One file per screen (Dashboard, NewRequisition, StockGRN, ...)
│   │   ├── components/           # Shared UI: layout, notification bell, dialogs, signature pad
│   │   ├── context/              # Auth context
│   │   └── lib/                  # API client, status labels, helpers
│   ├── package.json
│   └── .env.example
├── docs/                         # Project report (PDF) and screenshots
├── .gitignore
└── README.md
```

## Getting started

### Prerequisites

- **Python** 3.10 or newer
- **Node.js** 18 or newer, and **Yarn** (recommended; npm also works)
- **MongoDB** 6 or newer, running locally (`mongodb://localhost:27017`) or a MongoDB Atlas connection string

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# edit .env: set MONGO_URL, DB_NAME, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD ...
```

Create the base departments and the first Super Admin (a new database has no users, so you cannot sign in until you do this):

```bash
python create_super_admin.py
```

Start the API:

```bash
uvicorn server:app --reload --port 8001
```

The API is now at `http://localhost:8001/api` and interactive docs are at `http://localhost:8001/docs`.

### 2. Frontend

```bash
cd frontend
cp .env.example .env               # Windows: copy .env.example .env
yarn install                       # or: npm install
yarn start                         # or: npm start
```

Open `http://localhost:3000` and sign in with the Super Admin email and password from step 1.

> **Local HTTP tip:** keep `COOKIE_SECURE=false` in `backend/.env` while developing over plain `http://localhost`. Set it to `true` in production (HTTPS).

### 3. Production build

```bash
cd frontend
yarn build                         # outputs frontend/build, serve it with any static host
```

Run the backend with several workers behind HTTPS, for example:

```bash
uvicorn server:app --host 0.0.0.0 --port 8001 --workers 2
```

and set `FRONTEND_URL` to your real site address so CORS allows it.

## Configuration

### `backend/.env`

| Variable | Required | Description |
|---|---|---|
| `MONGO_URL` | yes | MongoDB connection string. |
| `DB_NAME` | yes | Database name. |
| `JWT_SECRET` | yes | Long random secret used to sign login tokens. |
| `FRONTEND_URL` | yes | Origin of the React app (CORS). `http://localhost:3000` is always allowed. |
| `COOKIE_SECURE` | no | `true` (default) or `false`. Use `false` only for local HTTP. |
| `ADMIN_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | for first run | Read by `create_super_admin.py` (it asks if they are missing). |
| `SEED_USER_PASSWORD` | no | Initial password for a user created without one (default `password123`, change it). |
| `REMINDER_SWEEP_MINUTES` | no | How often the approval-reminder check runs (default 15). |
| `EMERGENT_LLM_KEY` | optional | Key for the attachment storage service (see [Known limitations](#known-limitations)). |

### `frontend/.env`

| Variable | Description |
|---|---|
| `REACT_APP_BACKEND_URL` | Base URL of the backend, without `/api` (for example `http://localhost:8001`). |

### Business settings

The **PO MD limit** (default 50,000 BDT), the **PO Accounts limit** (default 50,000 BDT) and the **approval reminder time** (default 24 hours) are stored in the database (`system_settings`) and changed through the API:

| Setting | Endpoint (Super Admin) |
|---|---|
| PO MD limit | `PUT /api/settings/po-threshold` with `{"amount": 50000}` |
| PO Accounts limit | `PUT /api/settings/po-accounts-limit` with `{"amount": 50000}` |
| Reminder hours | `PUT /api/settings/reminder` with `{"reminder_hours": 24}` |

## First-time setup inside the app

Sign in as Super Admin, then:

1. **Organization > Departments** - the script created `IT`, `Purchase`, `Accounts`, `Admin` and `Primitek Group`. Add your other departments (HR, Sales, ...).
   The code looks up **`IT`**, **`Purchase`** and **`Primitek Group`** by exact name and **`Admin`** / **`Administration`** loosely, so do not rename those.
2. **Organization > Products** - build the product catalogue (type: IT Asset, IT Accessories, Network, Consumable, Furniture). Requisitions, stock, PR and PO all use these exact names.
3. **Organization > Users and Roles** - add the department heads, the Purchase Head, the Accounts Head, the MD and the IT team. Set **Can Raise PR** for IT PR handlers, **Can Create PO** for purchase staff, and an **IT team** for IT executives.
4. **Organization > Bulk Import** - load all remaining employees, then the assets they already hold, from the Excel/CSV templates. Download the generated credentials file to hand out temporary passwords.
5. **Approvals > Approver Management** - adjust which menu items each role can see, if needed.

Departments must have their heads in place, because the approval chain finds each approver by department.

## Useful scripts

| Script | Purpose |
|---|---|
| `backend/create_super_admin.py` | Creates the base departments and the first Super Admin. Safe to run again. |
| `backend/clear_db.py` | Deletes sample transactional data (requisitions, handovers, assets, GRNs ...). **Destructive.** Check the database name inside the file first. |
| `backend/fix_orphaned_handovers.py` | One-off repair for handovers confirmed without a linked requisition. |

## Security notes

- **Never commit `.env` files.** The `.gitignore` in this repository excludes them; use the `.env.example` files as templates. If a real `.env` was ever pushed, rotate `JWT_SECRET`, `ADMIN_PASSWORD` and `EMERGENT_LLM_KEY` immediately and remove it from the Git history.
- Passwords are stored as bcrypt hashes. Admin password resets issue a one-time temporary password, sign the user out everywhere, and force a new password at next login.
- Menu and API access are checked on the server for every request, not only hidden in the UI.
- Change `SEED_USER_PASSWORD` from its default and use `COOKIE_SECURE=true` behind HTTPS in production.

## Known limitations

- **File attachments** are stored through an external storage service configured by `EMERGENT_LLM_KEY` (see `init_storage` in `server.py`). Without it, uploading attachments will fail while the rest of the app works. For self-hosting, replace `put_object` / `get_object` with local disk or an S3-compatible store.
- No email or SMS alerts yet (notifications are in-app only).
- No self-service "Forgot password" by email; recovery is admin-assisted.
- No login rate limiting or account lockout yet.
- No automated test suite is included yet.
- The business limits above have no settings screen yet (API only).

## Roadmap

- Email / SMS notifications
- Email-based password reset
- Login lockout and rate limiting
- Settings screen for PO limits and reminder time
- Reports and charts (purchases, stock value, approval times) with Excel export
- Android app (for example a Capacitor wrapper) and internal-testing release
- Scheduled database backups

## License

Add your license here (for example MIT), or state that the project is private/internal.
