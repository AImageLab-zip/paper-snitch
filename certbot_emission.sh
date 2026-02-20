# New primary domain
DOMAIN="paper-snitch.online"
# Old domain (for transition period)
OLD_DOMAIN="paper-snitch.ing.unimore.it"
EMAIL="federico.bolelli@unimore.it"  # Update with your email

docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
    -d ${DOMAIN} \
    -d www.${DOMAIN} \
    -d ${OLD_DOMAIN} \
    -d www.${OLD_DOMAIN} \
    --email ${EMAIL} \
    --agree-tos