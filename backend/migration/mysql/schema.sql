-- =====================================================================================================
--  Requisitions -> MySQL 8.0   (schema v1)
--
--  Tables
--    requisitions          one row per requisition (scalar fields as real columns, rarely-queried blobs as JSON)
--    requisition_items     line items            (replaces requisitions.items[])
--    approval_steps        the approval chain    (replaces requisitions.approval_chain[], ordered by `seq`)
--    requisition_history   audit trail           (replaces requisitions.history[], ordered by `id`, append-only)
--
--  Design rules
--    * `id` (BIGINT) is the internal key used for joins. `public_id` (24 hex chars) is the id the API, the
--      frontend and the not-yet-migrated MongoDB collections (purchase_orders, handovers, users, ...) already use,
--      so migrated rows keep their old ObjectId string and nothing outside this module has to change.
--    * References to rows that still live in MongoDB (users, departments, po_id, handover_id ...) are plain
--      VARCHAR columns WITHOUT foreign keys. They become real foreign keys when those tables are migrated.
--    * Dates the user picks on a form are DATE; system timestamps are DATETIME(6) in UTC. A value that is not in the application's canonical format
--      (e.g. '2026-10-01' or a naive time) is kept verbatim in `extra._raw` so no information is lost.
--    * Anything the schema does not know about goes to the JSON `extra` column - the copy never drops data.
--    * Text columns use utf8mb4 (Bangla, emoji ...). Codes/ids are ascii_bin (exact, case-sensitive, like MongoDB).
-- =====================================================================================================

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS requisitions (
  id                              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id                       CHAR(24)    CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  requisition_no                  VARCHAR(40) NOT NULL,
  requisition_type                VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL,
  status                          VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

  -- who asked
  requisitioner_id                VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  requisitioner_name              VARCHAR(150) NULL,
  requisitioner_department_id     VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  requisition_for                 VARCHAR(150) NULL,

  -- dates
  created_at                      DATETIME(6) NULL,
  updated_at                      DATETIME(6) NULL,
  requisition_date                DATE NULL,                   -- picked on the form (YYYY-MM-DD)
  required_by_date                DATE NULL,                   -- picked on the form (YYYY-MM-DD)
  closed_at                       DATETIME(6) NULL,
  cancelled_at                    DATETIME(6) NULL,
  service_claimed_at              DATETIME(6) NULL,
  service_completed_at            DATETIME(6) NULL,

  -- request details
  requester_note                  TEXT NULL,
  overall_business_justification  TEXT NULL,
  delivery_location               VARCHAR(255) NULL,
  urgency_level                   VARCHAR(24) NULL,
  total_amount                    DECIMAL(14,2) NOT NULL DEFAULT 0,
  edit_count                      INT NULL,
  attachment_file_id              VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  attachment_name                 VARCHAR(255) NULL,
  attachment_path                 VARCHAR(512) NULL,

  -- purchase-requisition (PR) / purchase-order (PO) track
  pr_flow                         TINYINT(1) NULL,
  po_flow                         TINYINT(1) NULL,
  pr_needs_refile                 TINYINT(1) NULL,
  purchase_pr_no                  VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  pr_filed_by                     VARCHAR(150) NULL,
  pr_filed_by_id                  VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  pr_cancelled_by                 VARCHAR(150) NULL,
  pr_cancel_note                  TEXT NULL,
  po_id                           VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,     -- purchase_orders (Mongo)

  -- stock decision / handover
  fulfillment_type                VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  stock_check_at_submission       VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NULL,
  procurement_notes               TEXT NULL,
  allocated_by                    VARCHAR(150) NULL,
  stock_bypassed_by               VARCHAR(150) NULL,
  handover_id                     VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,     -- handovers (Mongo)

  -- requester cancel
  cancelled_by                    VARCHAR(150) NULL,
  cancel_note                     TEXT NULL,

  -- IT service tickets (requisition_type = 'service')
  it_team                         VARCHAR(40) NULL,
  service_assigned_to_id          VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  service_assigned_to_name        VARCHAR(150) NULL,
  service_completed_by            VARCHAR(150) NULL,

  -- corrections ("not received" flow)
  correction_case_id              VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  correction_of_requisition_id    VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,

  -- display-only structures, never filtered on: kept as JSON
  pr_attachment_file_ids          JSON NULL,
  allocated_item_details          JSON NULL,
  last_edit                       JSON NULL,
  revision_feedback               JSON NULL,
  pr_revision_feedback            JSON NULL,
  repair_request                  JSON NULL,                   -- external-repair request of an IT ticket

  extra                           JSON NULL,                   -- any field this schema does not know (+ `_raw` timestamps)

  PRIMARY KEY (id),
  UNIQUE KEY uq_requisitions_public_id (public_id),
  UNIQUE KEY uq_requisitions_no (requisition_no),
  KEY ix_req_created (created_at),
  KEY ix_req_status_created (status, created_at),
  KEY ix_req_requester_created (requisitioner_id, created_at),
  KEY ix_req_dept_created (requisitioner_department_id, created_at),
  KEY ix_req_pr_filed_by (pr_filed_by_id),
  KEY ix_req_pr_no (purchase_pr_no),
  KEY ix_req_po (po_id),
  KEY ix_req_handover (handover_id),
  KEY ix_req_service_queue (requisition_type, it_team, status),
  KEY ix_req_assignee (service_assigned_to_id, status),
  KEY ix_req_correction (correction_case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS requisition_items (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  requisition_id              BIGINT UNSIGNED NOT NULL,
  seq                         SMALLINT UNSIGNED NOT NULL,      -- 0-based position in the original items[] array
  product_type                VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NULL,
  product_name                VARCHAR(255) NULL,
  quantity                    INT NULL,
  rate                        DECIMAL(14,2) NULL,
  line_total                  DECIMAL(14,2) NULL,
  remarks                     TEXT NULL,
  category_id                 VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  -- what the requester asked for (New Requisition form)
  preferred_specification     TEXT NULL,
  brand_name                  VARCHAR(150) NULL,
  model                       VARCHAR(150) NULL,
  -- IT service lines
  priority                    VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL,
  request_type                VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  service_category            VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  request_detail              TEXT NULL,
  -- what the PR raiser filled in (Purchase Requisition form)
  category                    VARCHAR(64) NULL,
  detailed_specs              TEXT NULL,
  preferred_brand             VARCHAR(150) NULL,
  uom                         VARCHAR(24) NULL,
  estimated_unit_price        DECIMAL(14,2) NULL,
  line_date_required          DATE NULL,
  justification_remarks       TEXT NULL,
  extra                       JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_items_req_seq (requisition_id, seq),
  KEY ix_items_product (product_name(100)),
  CONSTRAINT fk_items_req FOREIGN KEY (requisition_id) REFERENCES requisitions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS approval_steps (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  requisition_id      BIGINT UNSIGNED NOT NULL,
  seq                 SMALLINT UNSIGNED NOT NULL,              -- 0-based position in approval_chain[] (step 0 = first approver)
  `level`             INT NULL,
  `role`              VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  label               VARCHAR(120) NULL,
  stage               VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  department_id       VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  approver_id         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  approver_name       VARCHAR(150) NULL,
  status              VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  note                TEXT NULL,
  pending_since       DATETIME(6) NULL,
  acted_at            DATETIME(6) NULL,
  reminded_at         DATETIME(6) NULL,
  acted_by_id         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  acted_by_name       VARCHAR(150) NULL,
  acted_as            VARCHAR(40) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_steps_req_seq (requisition_id, seq),
  KEY ix_steps_approver_status (approver_id, status),          -- "what is waiting for me"
  KEY ix_steps_stage (stage),
  KEY ix_steps_status (status),
  CONSTRAINT fk_steps_req FOREIGN KEY (requisition_id) REFERENCES requisitions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS requisition_history (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,   -- ascending id = chronological order (append-only)
  requisition_id      BIGINT UNSIGNED NOT NULL,
  `at`                DATETIME(6) NULL,
  by_name             VARCHAR(150) NULL,                         -- the Mongo key is `by`, a reserved word in SQL
  `action`            VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  note                TEXT NULL,
  `level`             INT NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  KEY ix_hist_req (requisition_id, id),
  KEY ix_hist_action (`action`),
  CONSTRAINT fk_hist_req FOREIGN KEY (requisition_id) REFERENCES requisitions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


-- =====================================================================================================
--  People tables (schema v2): departments, users, sidebar_permissions, password_resets
--  Same conventions as above: `public_id` keeps the existing 24-character id; unknown fields go to `extra`.
--  Real FOREIGN KEYS to these tables are added separately (python -m migration.mysql.migrate foreign-keys add),
--  only once users, departments and requisitions all live in MySQL and an orphan check is clean.
--  Emails and department names are case-sensitive (utf8mb4_0900_as_cs) exactly like the MongoDB lookups were;
--  the application lower-cases emails before it stores or looks them up.
-- =====================================================================================================

CREATE TABLE IF NOT EXISTS departments (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name                VARCHAR(150) COLLATE utf8mb4_0900_as_cs NOT NULL,
  code                VARCHAR(40) NULL,
  description         TEXT NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_departments_public_id (public_id),
  KEY ix_departments_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS users (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id                   CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name                        VARCHAR(150) NOT NULL,
  email                       VARCHAR(190) COLLATE utf8mb4_0900_as_cs NOT NULL,
  password_hash               VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NULL,
  role                        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  role_label                  VARCHAR(64) NULL,
  department_id               VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,   -- departments.public_id
  can_raise_pr                TINYINT(1) NULL,
  can_create_po               TINYINT(1) NULL,
  can_process_requisition     TINYINT(1) NULL,
  it_team                     VARCHAR(40) NULL,
  must_change_password        TINYINT(1) NULL,
  password_changed_at         DATETIME(6) NULL,
  sessions_valid_from         BIGINT NULL,                  -- epoch seconds: tokens issued before this are refused
  delegate_user_id            VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,   -- users.public_id
  delegate_from               DATE NULL,
  delegate_until              DATE NULL,
  created_at                  DATETIME(6) NULL,
  extra                       JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_public_id (public_id),
  UNIQUE KEY uq_users_email (email),
  KEY ix_users_dept_role (department_id, role),
  KEY ix_users_role (role),
  KEY ix_users_delegate (delegate_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS sidebar_permissions (
  role                VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  items               JSON NOT NULL,                        -- the menu keys an administrator saved for this role
  PRIMARY KEY (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS password_resets (                -- audit log; it must outlive the users, so no foreign keys
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id             VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  user_email          VARCHAR(190) NULL,
  reset_by            VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  reset_by_name       VARCHAR(150) NULL,
  `at`                DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  KEY ix_resets_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


-- =====================================================================================================
--  Catalog + supporting tables (schema v3): categories, products, counters, files, notifications,
--  purchase_orders
--  Same conventions: public_id keeps the existing 24-character ObjectId (except files, which use a UUID
--  string as their public id, and counters, which use a string key as primary identifier).
-- =====================================================================================================

CREATE TABLE IF NOT EXISTS categories (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name                VARCHAR(150) NOT NULL,
  department_id       VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  description         TEXT NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_categories_public_id (public_id),
  KEY ix_categories_name (name),
  KEY ix_categories_department (department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS products (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name                VARCHAR(255) NOT NULL,
  name_key            VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  product_type        VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  brand               VARCHAR(150) NULL,
  created_by          VARCHAR(150) NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_products_public_id (public_id),
  UNIQUE KEY uq_products_name_key (name_key),
  KEY ix_products_type (product_type),
  KEY ix_products_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS counters (
  counter_key         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,  -- e.g. "pr-2026", "po-2026"
  seq                 INT UNSIGNED NOT NULL DEFAULT 0,
  extra               JSON NULL,
  PRIMARY KEY (counter_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS files (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,  -- UUID string used by the API
  storage_path        VARCHAR(500) NOT NULL,
  original_filename   VARCHAR(255) NULL,
  content_type        VARCHAR(120) NULL,
  size                BIGINT UNSIGNED NULL,
  is_deleted          TINYINT(1) NOT NULL DEFAULT 0,
  uploaded_by         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_files_public_id (public_id),
  KEY ix_files_uploaded_by (uploaded_by),
  KEY ix_files_is_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS notifications (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id             VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  type                VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  status              VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  title               VARCHAR(255) NULL,
  message             TEXT NULL,
  asset_id            VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  asset_name          VARCHAR(255) NULL,
  requisition_id      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  handover_id         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  created_at          DATETIME(6) NULL,
  acted_at            DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_notifications_public_id (public_id),
  KEY ix_notifications_user_status (user_id, status),
  KEY ix_notifications_user_created (user_id, created_at),
  KEY ix_notifications_requisition_type (requisition_id, type),
  KEY ix_notifications_handover_type (handover_id, type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS purchase_orders (
  id                              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id                       CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  po_number                       VARCHAR(40) NOT NULL,
  requisition_id                  VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  vendor_id                       VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  vendor_name                     VARCHAR(200) NULL,
  contact_person                  VARCHAR(150) NULL,
  vendor_email                    VARCHAR(190) NULL,
  bin_tin                         VARCHAR(80) NULL,
  delivery_location               VARCHAR(255) NULL,
  attention_to                    VARCHAR(150) NULL,
  delivery_date                   DATE NULL,
  payment_terms                   VARCHAR(120) NULL,
  po_date                         DATE NULL,
  cs_reference_no                 VARCHAR(80) NULL,
  cs_attachment_file_ids          JSON NULL,
  items                           JSON NULL,
  special_terms_notes             TEXT NULL,
  sub_total                       DECIMAL(14,2) NULL,
  tax_percent                     DECIMAL(8,2) NULL,
  total_tax                       DECIMAL(14,2) NULL,
  discount_amount                 DECIMAL(14,2) NULL,
  transport_charge                DECIMAL(14,2) NULL,
  grand_total                     DECIMAL(14,2) NULL,
  status                          VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  approval_comments               JSON NULL,
  created_by                      VARCHAR(150) NULL,
  created_by_id                   VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  submitted_by                    VARCHAR(150) NULL,
  submitted_at                    DATETIME(6) NULL,
  threshold_at_submission         DECIMAL(14,2) NULL,
  reminder                        JSON NULL,
  created_at                      DATETIME(6) NULL,
  updated_at                      DATETIME(6) NULL,
  extra                           JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_po_public_id (public_id),
  UNIQUE KEY uq_po_number (po_number),
  KEY ix_po_requisition (requisition_id),
  KEY ix_po_status_created (status, created_at),
  KEY ix_po_created_by (created_by_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


-- =====================================================================================================
--  Inventory tables (schema v4): assets, handovers, correction_cases
-- =====================================================================================================

CREATE TABLE IF NOT EXISTS assets (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id                   CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name                        VARCHAR(255) NOT NULL,
  brand                       VARCHAR(150) NULL,
  serial_no                   VARCHAR(120) NULL,
  tag_id                      VARCHAR(120) NULL,
  category_id                 VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  specification               TEXT NULL,
  status                      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  condition_label             VARCHAR(40) NULL,                 -- `condition` is reserved in SQL
  assigned_to                 VARCHAR(150) NULL,
  assigned_to_user_id         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  assigned_department_id      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  assigned_at                 DATETIME(6) NULL,
  assigned_slip_no            VARCHAR(40) NULL,
  receipt_confirmed           TINYINT(1) NULL,
  receipt_confirmed_at        DATETIME(6) NULL,
  pending_receipt             TINYINT(1) NULL,
  pending_handover_id         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  pending_return_handover_id  VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  pending_return_slip_no      VARCHAR(40) NULL,
  assigned_to_tentative       VARCHAR(150) NULL,
  source_grn_id               VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  source                      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  remarks                     TEXT NULL,
  added_by                    VARCHAR(150) NULL,
  created_at                  DATETIME(6) NULL,
  extra                       JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_assets_public_id (public_id),
  KEY ix_assets_serial (serial_no),
  KEY ix_assets_tag (tag_id),
  KEY ix_assets_status_created (status, created_at),
  KEY ix_assets_name_status (name, status),
  KEY ix_assets_assigned_user (assigned_to_user_id, status),
  KEY ix_assets_assigned_to (assigned_to),
  KEY ix_assets_category (category_id),
  KEY ix_assets_source_grn (source_grn_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS handovers (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id                   CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  slip_no                     VARCHAR(40) NOT NULL,
  type                        VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NULL,
  employee_name               VARCHAR(150) NULL,
  employee_user_id            VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  department_id               VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  items                       JSON NULL,
  return_items                JSON NULL,
  return_received             TINYINT(1) NULL,
  remarks                     TEXT NULL,
  note                        TEXT NULL,
  handover_date               DATETIME(6) NULL,
  prepared_by                 VARCHAR(150) NULL,
  prepared_by_sign            VARCHAR(150) NULL,
  received_by_sign            VARCHAR(150) NULL,
  status                      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  requisition_id              VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  correction_case_ids         JSON NULL,
  confirmed_at                DATETIME(6) NULL,
  created_at                  DATETIME(6) NULL,
  extra                       JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_handovers_public_id (public_id),
  UNIQUE KEY uq_handovers_slip_no (slip_no),
  KEY ix_handovers_created (created_at),
  KEY ix_handovers_employee (employee_user_id),
  KEY ix_handovers_status (status),
  KEY ix_handovers_requisition (requisition_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS correction_cases (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id                   CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  case_no                     VARCHAR(40) NOT NULL,
  status                      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version                     INT NULL,
  requisition_id              VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  requisition_no              VARCHAR(40) NULL,
  original_handover_id        VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  original_slip_no            VARCHAR(40) NULL,
  employee_user_id            VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  employee_name               VARCHAR(150) NULL,
  department_id               VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  notification_id             VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  item                        JSON NULL,
  reason                      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  reason_label                VARCHAR(120) NULL,
  note                        TEXT NULL,
  attachment_file_id          VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  attachment_name             VARCHAR(255) NULL,
  responsible_it_id           VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  responsible_it_name         VARCHAR(150) NULL,
  attempts                    JSON NULL,
  failed_attempts             INT NULL,
  clarifications              JSON NULL,
  notes                       JSON NULL,
  events                      JSON NULL,
  procurement                 JSON NULL,
  rejections                  JSON NULL,
  reminders                   JSON NULL,
  escalated_at                DATETIME(6) NULL,
  escalations                 JSON NULL,
  created_at                  DATETIME(6) NULL,
  last_activity_at            DATETIME(6) NULL,
  closed_at                   DATETIME(6) NULL,
  closure                     JSON NULL,
  confirmed_at                DATETIME(6) NULL,
  status_before_clarification VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  extra                       JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_correction_cases_public_id (public_id),
  UNIQUE KEY uq_correction_cases_case_no (case_no),
  KEY ix_correction_status_created (status, created_at),
  KEY ix_correction_employee (employee_user_id),
  KEY ix_correction_notification (notification_id),
  KEY ix_correction_handover (original_handover_id),
  KEY ix_correction_requisition (requisition_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


-- =====================================================================================================
--  Final tables (schema v5): system_settings, grns, asset_history
-- =====================================================================================================

CREATE TABLE IF NOT EXISTS system_settings (
  setting_key         VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  payload             JSON NOT NULL,
  PRIMARY KEY (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS grns (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  grn_no              VARCHAR(40) NOT NULL,
  challan_no          VARCHAR(80) NULL,
  vendor_name         VARCHAR(200) NULL,
  received_date       DATETIME(6) NULL,
  delivery_location   VARCHAR(255) NULL,
  requisition_id      VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  items               JSON NULL,
  received_by         VARCHAR(150) NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_grns_public_id (public_id),
  UNIQUE KEY uq_grns_grn_no (grn_no),
  KEY ix_grns_created (created_at),
  KEY ix_grns_requisition (requisition_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS asset_history (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  asset_id            VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `at`                DATETIME(6) NULL,
  action              VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  by_name             VARCHAR(150) NULL,
  employee_name       VARCHAR(150) NULL,
  employee_user_id    VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  slip_no             VARCHAR(40) NULL,
  handover_id         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  source              VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  remarks             TEXT NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_asset_history_public_id (public_id),
  KEY ix_ah_asset (asset_id, `at`),
  KEY ix_ah_employee (employee_user_id),
  KEY ix_ah_at (`at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


-- =====================================================================================================
--  Final residual tables (schema v6): paper_records, saved_reports, report_access, import_batches
-- =====================================================================================================

CREATE TABLE IF NOT EXISTS paper_records (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  employee_id         VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  employee_name       VARCHAR(150) NULL,
  asset_ids           JSON NULL,
  file_ids            JSON NULL,
  kind                VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  notes               TEXT NULL,
  created_by          VARCHAR(150) NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_paper_public_id (public_id),
  KEY ix_paper_employee (employee_id),
  KEY ix_paper_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS saved_reports (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  title               VARCHAR(255) NULL,
  report_type         VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  definition          JSON NULL,
  audit               JSON NULL,
  created_by          VARCHAR(150) NULL,
  created_by_id       VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  created_at          DATETIME(6) NULL,
  updated_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_saved_reports_public_id (public_id),
  KEY ix_saved_reports_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS report_access (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  report_id           VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id             VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  status              VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  permissions         JSON NULL,
  last_opened_at      DATETIME(6) NULL,
  granted_by          VARCHAR(150) NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_report_access_public_id (public_id),
  KEY ix_ra_user_report (user_id, report_id),
  KEY ix_ra_report (report_id),
  KEY ix_ra_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE TABLE IF NOT EXISTS import_batches (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id           CHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  batch_id            VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  kind                VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
  filename            VARCHAR(255) NULL,
  by_name             VARCHAR(150) NULL,
  created_at          DATETIME(6) NULL,
  extra               JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_import_batches_public_id (public_id),
  KEY ix_import_batches_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;
