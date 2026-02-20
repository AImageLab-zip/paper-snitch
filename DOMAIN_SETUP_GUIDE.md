# Domain Configuration Guide for paper-snitch.online

## Step 1: Configure DNS on Aruba

Log into your Aruba domain management panel and configure the following DNS records:

### A Records (IPv4)
```
Type: A
Name: @
Value: YOUR_SERVER_IP
TTL: 14400 (or default)

Type: A
Name: www
Value: YOUR_SERVER_IP
TTL: 14400 (or default)
```

Replace `YOUR_SERVER_IP` with your server's public IP address (you can find it with `curl ifconfig.me`).

### DNS Propagation
DNS changes can take 1-48 hours to propagate globally. You can check status at:
- https://dnschecker.org
- https://www.whatsmydns.net

## Step 2: Update Configuration Files

### 2.1 Update Email Addresses
Edit the following files and replace `your-email@example.com` with your actual email:

**File: certbot_emission.sh**
```bash
EMAIL="your-actual-email@example.com"
```

**File: compose.prod.yml** (line 139)
```yaml
command: certonly --webroot -w /var/www/certbot --email your-actual-email@example.com -d paper-snitch.online -d www.paper-snitch.online --agree-tos --non-interactive
```

### 2.2 Create Production Environment File

1. Copy the template:
```bash
cp .env.prod.template .env.prod
```

2. Edit `.env.prod` and update these **REQUIRED** values:
```bash
nano .env.prod
```

**Critical settings to change**:
- `SECRET_KEY`: Generate a new one with:
  ```bash
  python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
  ```
- `MYSQL_ROOT_PASSWORD`: Set a strong password
- `MYSQL_PASSWORD`: Set a strong password (different from root)

**Already configured correctly** (verify):
- `DJANGO_ALLOWED_HOSTS=paper-snitch.online,www.paper-snitch.online`
- `CSRF_TRUSTED_ORIGINS=https://paper-snitch.online,https://www.paper-snitch.online`

**Optional** (configure if needed):
- `OPENAI_API_KEY`: If you use OpenAI features
- `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`: For email notifications

⚠️ **SECURITY**: Never commit `.env.prod` to git! Ensure it's in `.gitignore`.

## Step 3: Initial SSL Certificate Setup

### 3.1 Start Services Without SSL First
```bash
cd /home/administrator/papersnitch

# Start nginx and django (without SSL)
docker compose -f compose.prod.yml up -d nginx django-web mysql redis
```

### 3.2 Test HTTP Access
Visit http://paper-snitch.online to ensure basic connectivity works.

### 3.3 Obtain SSL Certificate
```bash
# Method 1: Using certbot_emission.sh
chmod +x certbot_emission.sh
./certbot_emission.sh

# Method 2: Using docker compose directly
docker compose -f compose.prod.yml run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    -d paper-snitch.online \
    -d www.paper-snitch.online \
    --email your-email@example.com \
    --agree-tos
```

### 3.4 Verify Certificate
```bash
sudo ls -la certbot/conf/live/paper-snitch.online/
```

You should see:
- fullchain.pem
- privkey.pem
- cert.pem
- chain.pem

## Step 4: Enable HTTPS

### 4.1 Restart Nginx
```bash
docker compose -f compose.prod.yml restart nginx
```

### 4.2 Start All Services
```bash
docker compose -f compose.prod.yml up -d
```

### 4.3 Verify HTTPS
Visit https://paper-snitch.online - you should see a secure connection.

## Step 5: Enable Auto-Renewal

The `certbot-renew` service in docker-compose will automatically renew certificates every 12 hours.

Verify it's running:
```bash
docker ps | grep certbot-renew
```

## Troubleshooting

### DNS Not Resolving
```bash
# Check if DNS has propagated
nslookup paper-snitch.online
dig paper-snitch.online

# If not resolving, wait longer or check Aruba DNS settings
```

### Certificate Errors
```bash
# Check nginx logs
docker logs nginx-prod

# Check certbot logs
docker logs certbot-prod

# Common issue: Port 80 not accessible
# Make sure your firewall allows ports 80 and 443
sudo ufw status
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

### Nginx Won't Start
```bash
# Test nginx configuration
docker exec nginx-prod nginx -t

# View detailed logs
docker logs nginx-prod --tail 100
```

## Step 6: Migration Checklist

- [ ] DNS A records configured in Aruba
- [ ] DNS propagated (check with dnschecker.org)
- [ ] Email addresses updated in config files
- [ ] Django ALLOWED_HOSTS updated
- [ ] HTTP access working
- [ ] SSL certificate obtained
- [ ] HTTPS access working
- [ ] Auto-renewal service running
- [ ] Old domain (paper-snitch.ing.unimore.it) redirected or decommissioned

## Quick Commands Reference

```bash
# Check DNS resolution
nslookup paper-snitch.online

# Get server IP
curl ifconfig.me

# View service status
docker compose -f compose.prod.yml ps

# View logs
docker compose -f compose.prod.yml logs -f nginx
docker compose -f compose.prod.yml logs -f django-web

# Restart services
docker compose -f compose.prod.yml restart

# Force certificate renewal (for testing)
docker compose -f compose.prod.yml run --rm certbot renew --force-renewal

# Stop all services
docker compose -f compose.prod.yml down
```

## Security Notes

1. **Firewall**: Ensure ports 80 and 443 are open
2. **Email**: Use a valid email for Let's Encrypt notifications
3. **Backups**: Keep backups of `certbot/conf` directory
4. **Monitoring**: Set up uptime monitoring (e.g., UptimeRobot, Pingdom)

## Support Resources

- Let's Encrypt: https://letsencrypt.org/docs/
- Nginx Documentation: https://nginx.org/en/docs/
- Aruba Support: https://www.aruba.it/assistenza.aspx
