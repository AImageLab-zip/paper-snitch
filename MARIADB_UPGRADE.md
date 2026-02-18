# MariaDB 11.7 Upgrade Guide - Dev Stack

## What Changed

1. **compose.dev.yml**: Updated mysql service from `mysql:latest` to `mariadb:11.7`
2. **Added command flags**: 
   - `--vector-ann-search=ON` (enables vector similarity search)
   - Character set configs for utf8mb4 compatibility
3. **.env.local**: Added MariaDB environment variables (MARIADB_* prefix)

## Django Compatibility

✅ **No Django changes needed** - MariaDB is 100% MySQL-compatible
- Same driver: `django.db.backends.mysql`
- Same connection protocol
- Same SQL dialect

## Migration Steps

### Step 1: Backup Current Database

```bash
cd /home/administrator/papersnitch

# Create backup directory
mkdir -p backups

# Backup all databases
docker exec mysql-dev-bolelli mysqldump \
  -u root \
  -prootpassword \
  --all-databases \
  --routines \
  --triggers \
  --events \
  > backups/mysql_backup_$(date +%Y%m%d_%H%M%S).sql

echo "Backup completed: backups/mysql_backup_*.sql"
```

### Step 2: Stop Current Stack

```bash
docker-compose -f compose.dev.yml --env-file .env.local down
```

### Step 3: Backup Data Directory (Extra Safety)

```bash
# Optional but recommended
sudo cp -r mysql_dev/lib mysql_dev/lib.backup.$(date +%Y%m%d)
```

### Step 4: Clear Data Directory for MariaDB

```bash
# MariaDB needs a fresh data directory
sudo rm -rf mysql_dev/lib/*
```

### Step 5: Start MariaDB Container

```bash
# Start with updated compose file (already updated)
docker-compose -f compose.dev.yml --env-file .env.local up -d mysql

# Wait for MariaDB to initialize
echo "Waiting for MariaDB to initialize..."
sleep 10

# Check logs
docker logs mysql-dev-bolelli
```

### Step 6: Restore Database

```bash
# Find your backup file
BACKUP_FILE=$(ls -t backups/mysql_backup_*.sql | head -1)
echo "Restoring from: $BACKUP_FILE"

# Restore data
docker exec -i mysql-dev-bolelli mysql \
  -u root \
  -prootpassword \
  < "$BACKUP_FILE"

echo "Database restored"
```

### Step 7: Verify MariaDB Version & Vector Support

```bash
# Check MariaDB version
docker exec mysql-dev-bolelli mysql \
  -u root \
  -prootpassword \
  -e "SELECT VERSION();"

# Verify vector search is enabled
docker exec mysql-dev-bolelli mysql \
  -u root \
  -prootpassword \
  -e "SHOW VARIABLES LIKE 'vector%';"
```

### Step 8: Start Full Stack

```bash
# Start all services
docker-compose -f compose.dev.yml --env-file .env.local up -d

# Check all containers are running
docker ps
```

### Step 9: Run Django Migrations (Verify)

```bash
# Django migrations should detect no changes
docker exec django-web-dev-bolelli python manage.py migrate

# Verify database connection
docker exec django-web-dev-bolelli python manage.py shell -c "
from django.db import connection
cursor = connection.cursor()
cursor.execute('SELECT VERSION()')
print('Database:', cursor.fetchone()[0])
"
```

### Step 10: Test Application

```bash
# Access the application
# http://localhost:8000

# Check:
# ✅ Login works
# ✅ Conference list loads
# ✅ Papers display correctly
# ✅ Workflow starts successfully
```

## Rollback (If Needed)

If something goes wrong:

```bash
# Stop containers
docker-compose -f compose.dev.yml --env-file .env.local down

# Restore backup data
sudo rm -rf mysql_dev/lib/*
sudo cp -r mysql_dev/lib.backup.YYYYMMDD/* mysql_dev/lib/

# Revert compose.dev.yml to use mysql:latest
# (or restore from git)

# Restart with MySQL
docker-compose -f compose.dev.yml --env-file .env.local up -d
```

## Verification Checklist

After upgrade, verify:

- [ ] MariaDB container is running: `docker ps | grep mysql`
- [ ] Version is 11.7+: `docker exec mysql-dev-bolelli mysql --version`
- [ ] Vector search enabled: Check `SHOW VARIABLES LIKE 'vector%';`
- [ ] Django connects: Application loads
- [ ] Data intact: Check conference count, paper count
- [ ] Migrations clean: `python manage.py migrate` shows no changes
- [ ] Workflows work: Start a workflow run

## Expected Output

**MariaDB Version:**
```
MariaDB 11.7.x-MariaDB
```

**Vector Search Variables:**
```
| Variable_name      | Value |
|--------------------|-------|
| vector_ann_search  | ON    |
```

## Next Steps After Successful Upgrade

1. Add `PaperEmbedding` model for vector storage
2. Create embedding generation service
3. Integrate RAG search into workflow analysis
4. Test vector similarity queries

## Troubleshooting

**Container fails to start:**
- Check logs: `docker logs mysql-dev-bolelli`
- Verify env vars are set correctly in .env.local
- Ensure data directory is writable

**Restore fails:**
- Check backup file exists and is valid
- Verify MariaDB is fully initialized (wait 30 seconds)
- Try restoring individual databases instead of --all-databases

**Django can't connect:**
- Verify DATABASE_HOST=mysql in .env.local
- Check mysql container is in same network
- Test connection: `docker exec django-web-dev-bolelli ping mysql`
