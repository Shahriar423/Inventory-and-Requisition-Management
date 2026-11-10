# Backend structure

Run: `uvicorn server:app --reload` (from this folder). Setup: `MYSQL_SETUP.md`.

```
server.py              entry point - just exposes `app`
ims/
  main.py              FastAPI app, CORS, error handlers, startup (checks every table) / shutdown, /api/health
  database.py          loads backend/.env
  ids.py               record ids: 24 hex characters, stored in each table's `public_id` column
  common.py            shared setup: auth helpers, constants, models, helpers
  repositories/
    <name>.py          the stable import name for each table's repository (re-exports the MySQL implementation)
    mysql/             the MySQL implementation, one file per table
      engine.py        async SQLAlchemy engine (MYSQL_URL), transactions at READ COMMITTED
      tables.py        SQLAlchemy table definitions (the schema itself is migration/mysql/schema.sql)
      catalog.py       which keys of a record are columns; everything else lives in the JSON `extra` column
      rows.py          record <-> row conversion
      clauses.py       filter dict -> SQL for requisitions
      flat.py          FlatTable: shared reads/writes for one-row-per-record tables (assets, handovers, notifications, ...)
  modules/             routes, one file per feature (auth, users, catalog, requisitions, purchase_orders, inventory, ...)
migration/mysql/       schema.sql, the schema tool, and the legacy one-time MongoDB import
tests/                 pytest suite (needs MYSQL_TEST_URL)
```

Rules
* Route modules never write SQL. They call a repository (`asset_repo.count_available(name)`, `handover_repo.get(id)` ...).
  Every query for a table lives in `ims/repositories/mysql/<table>.py`.
* Business rules (who may do what, which status comes next) stay in the route module; repositories only store and read.
* A feature module may import from `ims.common`, never from another feature module.
* New endpoints go in the module for their URL; the import order in `ims/main.py` is the route-matching order.

How a record is stored
* A record is a plain dict (`_id` is an `ObjectId`). Known keys are typed columns; any other key is kept in the table's
  JSON `extra` column, so adding a field to a record needs no schema change. A field that must be searched or sorted on
  should get a real column (add it to `schema.sql` and `catalog.py`).
* Updates read the record under a row lock (`SELECT ... FOR UPDATE`), apply the changes and write it back, so a field set
  to `None` is cleared and fields you did not mention are kept. Guarded updates (`asset_repo.update_if(id, {"status": "in_stock"}, {...})`)
  check the guard on the locked row and return 0 when it did not hold - answer 409 in that case.
* Filter dicts (`asset_repo.find({"status": {"$in": [...]}, "$or": [...]})`) are turned into SQL. Only columns can be
  filtered; a key that is not a column supports equality / `$in` only (checked in Python) and anything fancier raises
  `UnsupportedFilter` instead of silently matching nothing.

Tests
  See MYSQL_SETUP.md section 4. Golden-state tests (`tests/golden/*.json`) drive the real API and compare the stored
  records with a frozen snapshot. If a change is intended, review the diff, then re-record: `UPDATE_GOLDEN=1 pytest tests/<file>`.
