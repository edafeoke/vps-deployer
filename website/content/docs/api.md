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
| GET | `/api/projects/{project}/ssl` |
| POST | `/api/projects/{project}/ssl` |
| POST | `/api/ssl/renew` |
| GET | `/api/github/status` |
| POST | `/api/github/configure` |
| GET | `/api/github/repos` |
| POST | `/api/github/webhook` |

There is no `POST /execute` and no arbitrary shell endpoint.
