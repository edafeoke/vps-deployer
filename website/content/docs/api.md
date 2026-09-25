---
title: API
summary: Localhost JSON API and HTML dashboard.
---

The API binds to `127.0.0.1:5100`. Nginx may proxy a hostname or the VPS IP to that address after `vps-deployer dashboard enable`. Public requests require a password. `/health` and `POST /api/github/webhook` stay reachable without the dashboard login.

Interactive docs on the VPS: `http://127.0.0.1:5100/docs`.

## HTML (this VPS only)

| Path | Purpose |
| --- | --- |
| `GET /` | Dashboard overview |
| `GET /login` | Public dashboard sign-in |
| `GET /projects` | Projects |
| `GET /projects/{name}` | One project |
| `GET /doctor` | Doctor |

## JSON

| Method | Path |
| --- | --- |
| GET | `/health` |
| GET | `/api/status` |
| GET | `/api/system/doctor` |
| GET | `/api/host/nginx` |
| GET | `/api/host/nginx/config?config=sites-available/example` |
| POST | `/api/host/nginx/action` |
| GET | `/api/host/services` |
| POST | `/api/host/services/action` |
| POST | `/api/host/import` |
| GET | `/api/projects` |
| POST | `/api/projects` |
| GET | `/api/projects/{project}` |
| DELETE | `/api/projects/{project}` |
| POST | `/api/projects/{project}/deploy` |
| GET | `/api/projects/{project}/deployments` |
| GET | `/api/projects/{project}/logs` |
| POST | `/api/projects/{project}/rollback` |
| POST | `/api/projects/{project}/start` |
| POST | `/api/projects/{project}/stop` |
| POST | `/api/projects/{project}/restart` |
| GET | `/api/projects/{project}/service` |
| GET | `/api/projects/{project}/service/logs` |
| GET | `/api/projects/{project}/domains` |
| POST | `/api/projects/{project}/domains` |
| DELETE | `/api/projects/{project}/domains/{hostname}` |
| POST | `/api/projects/{project}/nginx` |
| GET | `/api/projects/{project}/nginx` |
| PUT | `/api/projects/{project}/nginx` |
| DELETE | `/api/projects/{project}/nginx` |
| GET | `/api/projects/{project}/ssl` |
| POST | `/api/projects/{project}/ssl` |
| POST | `/api/projects/{project}/ssl/external` |
| POST | `/api/ssl/renew` |
| GET | `/api/github/status` |
| POST | `/api/github/configure` |
| GET | `/api/github/repos` |
| POST | `/api/github/webhook` |

There is no `POST /execute` and no arbitrary shell endpoint.

Host Nginx actions take `{"id":"sites-available/example","revision":"<hash from GET>","action":"save-reload","content":"..."}`. Supported actions are `test`, `reload`, `save`, `save-reload`, `enable`, `disable`, `delete`. Test/reload are global and need no file/revision. Disable/delete require `confirm` equal to `id`. Changes to deployed-project configs use the existing project validation/persistence path. Backups and action results are returned; stale/invalid operations return 422.

Service actions take `{"unit":"example.service","action":"stop","confirm":"example.service"}`; start/stop/restart are supported and stop/restart require matching confirmation. Critical infrastructure units are rejected by the helper. Import takes `{"config":"sites-available/example","name":"existing-app","unit":"example.service"}`; omit `unit` for a static site. These routes require the same public dashboard authentication and reject cross-origin mutation requests.

`GET .../nginx` returns the installed `content`, `path`, `installed`, `custom`, deployment paths, roots, upstreams, and TLS file paths. `PUT` takes `{"content":"..."}`, validates and applies the site, and persists the override. `DELETE` restores generated config. The existing `POST` reapplies saved custom or generated config.

`POST .../ssl/external` takes `{"certificate":"/home/ubuntu/certificates/origin.pem","certificate_key":"/home/ubuntu/certificates/origin.key"}`. These are source paths on the VPS; the helper copies and validates the files into unique project-scoped paths automatically. `GET .../ssl` includes `provider`, `certificate`, and `certificate_key` destination paths. Validation errors return 422; missing domains return 409, missing projects 404, and Nginx application failures 502. Transferred sites can replace an existing explicit TLS pair through this route. These routes share the dashboard's authentication boundary.

`POST /api/host/handover` takes `{"config":"sites-available/old-app","project":"replacement","revision":"<hash from config GET>","units":["old-app.service"],"confirm":"sites-available/old-app"}`. It returns the queued deployment and message; watch `/api/projects/replacement/deployments` and logs for completion. The target must have no domains or active deployment. The worker deploys and health-checks it before transferring the existing Nginx site, TLS files and domains and stopping the selected old services. Omit units only for a static source. A matching `confirm` is mandatory and cross-origin requests are rejected. See [handover constraints and recovery](/docs/nginx).
