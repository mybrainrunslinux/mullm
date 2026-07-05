# mullm.com Nginx Sketch

This serves immutable release constraints while keeping a convenient top-level alias.

```nginx
server {
    listen 80;
    server_name mullm.com www.mullm.com;
    return 301 https://mullm.com$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mullm.com;

    root /var/www/mullm.com;
    index index.html;

    location = /constraints.txt {
        add_header Cache-Control "no-cache";
        try_files /releases/1.0.0/constraints.txt =404;
    }

    location /releases/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Expected upload layout:

```text
/var/www/mullm.com/index.html
/var/www/mullm.com/releases/1.0.0/constraints.txt
```

Install command:

```bash
python -m pip install mullm==1.0.0 -c https://mullm.com/constraints.txt
```

For fully reproducible enterprise docs, prefer:

```bash
python -m pip install mullm==1.0.0 -c https://mullm.com/releases/1.0.0/constraints.txt
```
