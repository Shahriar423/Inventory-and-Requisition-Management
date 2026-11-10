# Run from the backend folder:  powershell -ExecutionPolicy Bypass -File .\cleanup_stale_files.ps1
$stale = @(
 'ims\modules\common.py','ims\modules\main.py','ims\modules\database.py',
 'ims\repositories\departments_mongo.py','ims\repositories\requisitions_mongo.py','ims\repositories\users_mongo.py',
 'ims\repositories\sidebar_permissions_mongo.py','ims\repositories\mysql\residual.py','ims\repositories\mysql\compat.py',
 'fix_orphaned_handovers.py','quarantine.jsonl','requirements-mysql.txt'
)
$stale += (Get-ChildItem .\ims\repositories -Filter *_mongo.py -ErrorAction SilentlyContinue | ForEach-Object { "ims\repositories\$($_.Name)" })
$stale | Sort-Object -Unique | ForEach-Object { if (Test-Path $_) { Remove-Item $_ -Force; "removed $_" } }
Get-ChildItem . -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
"done - now re-run the grep"
