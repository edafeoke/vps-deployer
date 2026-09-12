---
title: Nginx
summary: How site files are written, tested, and reloaded.
---

Each project gets `vps-deployer-<project>.conf` in nginx sites-available/enabled.

HTTP (`listen 80`) either proxies a process app to `127.0.0.1:<port>` or serves static files from `/var/www/apps/<project>/current`. HTTPS adds `listen 443 ssl`.

The privileged helper installs the site, runs `nginx -t`, and reloads. A failed test rolls back that site file and leaves other sites untouched.

`include`, `alias`, and shell metacharacters are rejected. `proxy_pass` may only target `127.0.0.1` on ports `33000–33999`. TLS files must be the Let's Encrypt paths for that hostname.
