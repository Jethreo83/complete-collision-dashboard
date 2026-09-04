#!/bin/bash
set -e
cd /c/Users/jedgr/Documents/complete-collision-dashboard-live
PROD_URL=$(npx --yes neonctl@latest connection-string production --project-id aged-art-92489373 --role-name neondb_owner --database-name neondb)
echo "Target host (must be production ep-damp-bird-a5vtcqmv): "
echo "$PROD_URL" | cut -d'@' -f2 | cut -d'/' -f1
export CC_PROD_REAL="$PROD_URL"
echo "=== Applying rollback ==="
python scripts/run_sql.py CC_PROD_REAL scripts/006_ROLLBACK.sql
echo "=== Post-rollback state check ==="
python scripts/run_sql.py CC_PROD_REAL scripts/check_state.sql
