# MySQL setup (Windows + XAMPP)

The application stores everything in **MySQL 8.0**. XAMPP's database is MariaDB, which this project is not built for, so
install MySQL 8.0 next to XAMPP on another port (**3307**) and leave XAMPP alone. Run the commands in PowerShell from the
`backend` folder with the virtual environment active.

## 1. Install MySQL 8.0 (once)
1. Download **MySQL Installer for Windows** from <https://dev.mysql.com/downloads/installer/>.
2. **Custom** -> add **MySQL Server 8.0.x** (and **MySQL Workbench** if you want a visual tool).
3. *Type and Networking*: Development Computer, **Port = 3307**. *Authentication*: keep strong password encryption, set a root password.
4. Check: `& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p --port=3307 --protocol=TCP -e "SELECT VERSION();"` must print `8.0.x`.

## 2. Create the database and a limited user (once)
```sql
CREATE DATABASE ims CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'imsdev'@'localhost' IDENTIFIED BY 'ChangeMe_123';
GRANT ALL PRIVILEGES ON ims.*          TO 'imsdev'@'localhost';   -- the application's database
GRANT ALL PRIVILEGES ON `ims\_test%`.* TO 'imsdev'@'localhost';   -- scratch databases the automated tests create and drop
```

## 3. Packages, settings, tables
```powershell
pip install -r requirements.txt
copy .env.example .env        # then edit it: MYSQL_URL and JWT_SECRET
python -m migration.mysql.migrate schema      # creates every table (safe to repeat)
uvicorn server:app --reload
```
`MYSQL_URL=mysql://imsdev:ChangeMe_123@127.0.0.1:3307/ims` - percent-encode special characters in the password (`#` -> `%23`, `@` -> `%40`).
On start-up the server checks every table and stops with instructions if MySQL is unreachable or a table is missing.
Check the running server: `GET /api/health`.

## 4. Automated tests
```powershell
pip install -r requirements-dev.txt
$env:MYSQL_TEST_URL = "mysql://imsdev:ChangeMe_123@127.0.0.1:3307/ims_test"
pytest
```
Each test worker builds its own throw-away database (`ims_test_gw0`, ...) from `migration/mysql/schema.sql`; your real data is never touched.
Without `MYSQL_TEST_URL` the database tests are skipped.

## 5. Optional: foreign keys
`python -m migration.mysql.migrate foreign-keys check` reports rows that would violate them; `add` / `drop` switch them on / off.

## 6. Importing old MongoDB data (one time, legacy)
Only needed if you still have data in MongoDB. The application itself never talks to MongoDB.
```powershell
pip install -r migration\mysql\requirements-migration.txt     # adds pymongo
# MONGO_URL and DB_NAME are read from .env (or pass --mongo-url / --mongo-db)
python -m migration.mysql.migrate copy --dry-run
python -m migration.mysql.migrate copy
python -m migration.mysql.migrate verify                      # must end with RESULT: OK
```

## 7. Clearing test data
`python clear_db.py` deletes requisitions, stock, slips, POs, notifications and files (after you type the database name) and keeps users, departments, the catalog and settings.
