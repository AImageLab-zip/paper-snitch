# Quick Start: Domain Migration to paper-snitch.online

**✅ BOTH DOMAINS SUPPORTED**: This configuration supports both the old university domain (`paper-snitch.ing.unimore.it`) and new domain (`paper-snitch.online`) simultaneously during the transition period.

Follow these steps in order. ⚠️ Do not skip steps!

## 1. Find Your Server IP
```bash
curl ifconfig.me
```
Write down this IP address: `________________`

## 2. Configure DNS in Aruba Panel

Log in to your Aruba control panel and add these DNS records for the **NEW** domain:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | @ | [YOUR_SERVER_IP] | 3600 |
| A | www | [YOUR_SERVER_IP] | 3600 |

**Note**: Keep the old domain's DNS records (`paper-snitch.ing.unimore.it`) pointing to the same server IP. Both domains will work simultaneously.

Wait 5-10 minutes, then verify DNS propagation:
```bash
nslookup paper-snitch.online
dig paper-snitch.online +short
```

## 3. Create Production Environment File

```bash
cd /home/administrator/papersnitch
cp .env.prod.template .env.prod
nano .env.prod
```

**Update these values**:
```bash
# Generate a new secret key:
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Copy the output and paste it in .env.prod as SECRET_KEY
# Also set strong passwords for MYSQL_ROOT_PASSWORD and MYSQL_PASSWORD
```

**Verify these are correct**:
- `DJANGO_ALLOWED_HOSTS=paper-snitch.online,www.paper-snitch.online,paper-snitch.ing.unimore.it,www.paper-snitch.ing.unimore.it`
- `CSRF_TRUSTED_ORIGINS=https://paper-snitch.online,https://www.paper-snitch.online,https://paper-snitch.ing.unimore.it,https://www.paper-snitch.ing.unimore.it`

Save and exit (Ctrl+X, Y, Enter).

## 4. Update Email Addresses

```bash
# Edit certbot script
nano certbot_emission.sh
```
Change line 5: `EMAIL="your-actual-email@example.com"`

```bash
# Edit compose file
nano compose.prod.yml
```
Change line 139: Replace `your-email@example.com` in the certbot command

## 5. Ensure Firewall Allows HTTP/HTTPS

```bash
sudo ufw status
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

## 6. Start Services (HTTP Only First)

```bash
# Stop any existing containers
docker compose -f compose.prod.yml down

# Start services
docker compose -f compose.prod.yml up -d mysql redis grobid
sleep 10  # Wait for MySQL to initialize

docker compose -f compose.prod.yml up -d django-web celery-worker celery-beat
sleep 5

docker compose -f compose.prod.yml up -d nginx
```

## 7. Test HTTP Access

```bash
curl -I http://paper-snitch.online
```
You should see a redirect to HTTPS (301 or 302). This is good!

## 8. Obtain SSL Certificate

```bash
chmod +x certbot_emission.sh
./certbot_emission.sh
```

**Expected output**: "Successfully received certificate"

## 9. Start All Services with SSL

```bash
docker compose -f compose.prod.yml up -d
```

## 10. Verify HTTPS Works

Test both domains:
```bash
curl -I https://paper-snitch.online
curl -I https://paper-snitch.ing.unimore.it
```
Both should return: `HTTP/2 200` or `HTTP/1.1 200`

Open in browser:
- https://paper-snitch.online ✅
- https://paper-snitch.ing.unimore.it ✅

## 11. Verify Auto-Renewal

```bash
docker ps | grep certbot
```
You should see `certbot-renew` container running.

---

## Troubleshooting

### DNS not propagating
```bash
# Check DNS from external server
dig paper-snitch.online @8.8.8.8 +short
```
If empty, wait longer (up to 24 hours max).

### Certificate error
```bash
# Check Nginx logs
docker logs nginx-prod

# Check certbot logs
docker logs certbot-prod
```

### Django errors
```bash
# Check app logs
docker logs django-web-prod

# Check database
docker exec -it mysql-prod mysql -u root -p
```

### Port conflicts
```bash
# Check what's using ports 80/443
sudo netstat -tlnp | grep ':80\|:443'
```

---

## Quick Commands Reference

```bash
# View all containers
docker ps -a

# View logs
docker logs -f nginx-prod
docker logs -f django-web-prod

# Restart services
docker compose -f compose.prod.yml restart nginx
docker compose -f compose.prod.yml restart django-web

# Stop everything
docker compose -f compose.prod.yml down

# Start everything
docker compose -f compose.prod.yml up -d

# Rebuild and restart
docker compose -f compose.prod.yml up -d --build

# Check certificate expiry
docker exec certbot-prod certbot certificates
```

---

## Security Checklist

- [ ] .env.prod is NOT in git (check with: `git status`)
- [ ] Firewall is enabled: `sudo ufw status`
- [ ] Only ports 22, 80, 443 are open
- [ ] SSL certificate auto-renews (certbot-renew container running)
- [ ] SECRET_KEY is unique and strong (64+ chars)
- [ ] Database passwords are strong
- [ ] DEBUG=False in .env.prod

---

## Migration Complete! 🎉

Your application is now accessible via **BOTH domains**:

**New Domain (Aruba)**:
- https://paper-snitch.online ✅
- https://www.paper-snitch.online ✅

**Old Domain (University - transition)**:
- https://paper-snitch.ing.unimore.it ✅
- https://www.paper-snitch.ing.unimore.it ✅

All domains redirect to HTTPS and share the same SSL certificate.

### When to Decommission the Old Domain

Once you're ready to fully migrate:
1. Update all external links and documentation
2. Notify users of the domain change
3. Remove old domain from configuration files:
   - [nginx/nginx.conf](nginx/nginx.conf) - Remove from `server_name` directives
   - [.env.prod](.env.prod) - Remove from `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
   - [certbot_emission.sh](certbot_emission.sh) - Remove `OLD_DOMAIN` variable and `-d` flags
   - [compose.prod.yml](compose.prod.yml) - Remove old domain from certbot command
4. Optionally set up 301 redirect from old→new domain
