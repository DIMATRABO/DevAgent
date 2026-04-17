# CI/CD Pipeline Strategy — enginchantier.ma

**Author:** CEO Agent  
**Date:** 2026-04-17  
**Status:** Draft — pending Architect verification of assumptions

---

## 1. Situation

### Current State (broken)
| Layer | Current behavior | Problem |
|-------|-----------------|---------|
| Backend | `develop → main` = auto-deploy to **production** `api.enginchantier.ma` | No staging gate. Every merge hits prod. |
| Frontend | Any push → Vercel = auto-deploy to `engin-ma-front.vercel.app` | No environment separation. |
| Sandbox | `sandbox.enginchantier.ma` exists but nothing runs there | Wasted asset. |

### Target State
| Branch | Backend | Frontend |
|--------|---------|----------|
| `develop` | Auto-deploy → **sandbox** (sandbox DB) | Auto-deploy → Vercel **preview/staging** env |
| `main` | Manual approval button in GitHub → **production** `api.enginchantier.ma` | Vercel **production** |

---

## 2. Branch Strategy

**Recommended:** Two-branch model (simpler, less merge overhead)

```
develop ──► (auto) sandbox.enginchantier.ma
   │
   └── PR review ──► main ──► GitHub Environment "production" approval button
                              └── (approved) ──► api.enginchantier.ma
```

The "button in GitHub" = **GitHub Environments** with a required reviewer.
When a workflow targets the `production` environment, GitHub pauses and shows:
> "This workflow is waiting for your review" → [Approve and deploy] button.

No need for a separate `prod` branch — the approval gate on `main` achieves the UX you want.

---

## 3. Backend Pipeline Design

### Sandbox Deploy (automatic on `develop`)
```
push to develop
  → GitHub Actions: backend-sandbox.yml
  → Build Docker image
  → Push to Docker Hub (tag: sandbox)
  → SSH to THIS SAME VPS (same host as production)
  → docker pull + docker-compose -f docker-compose.sandbox.yml up -d
  → Uses SANDBOX_DATABASE_URL (separate Postgres container, port 5433)
  → Sandbox runs on port 8001 (or internal, proxied via Traefik/nginx)
```

### Production Deploy (manual approval on `main`)
```
push to main
  → GitHub Actions: backend-production.yml
  → Targets GitHub Environment: "production"
  → [PAUSE — shows approval button]
  → [You click Approve]
  → Build Docker image
  → Push to Docker Hub (tag: latest)
  → SSH to THIS SAME VPS
  → docker pull + docker-compose up -d
  → Uses PROD_DATABASE_URL
```

**Same-VPS note:** Both workflows SSH to the same host. The only difference is which `docker-compose` file they run and which env vars they inject. Architect must assign distinct ports and Docker networks so the two stacks cannot interfere.

---

## 4. Frontend Pipeline Design

Vercel supports **multiple environments** natively (Preview / Production):
- Push `develop` → Vercel preview/staging URL
- Push `main` → Vercel production (`engin-ma-front.vercel.app` or custom domain)

This requires configuring the Vercel project to set `main` as the production branch
and pointing env vars per environment (sandbox API URL vs prod API URL).

**Docker Hub note for frontend:** Not needed for Vercel deployments.
If self-hosting the frontend becomes a future requirement, the pipeline can be extended.
Architect to confirm intent with user.

---

## 5. GitHub Secrets Required

### Backend repo (new secrets to add)
| Secret Name | Value to set | Notes |
|-------------|-------------|-------|
| `DOCKER_HUB_USERNAME` | Your Docker Hub username | May already exist |
| `DOCKER_HUB_TOKEN` | Docker Hub access token | May already exist |
| `SANDBOX_SSH_HOST` | IP or hostname of sandbox server | **NEW** |
| `SANDBOX_SSH_USER` | SSH username on sandbox server | **NEW** |
| `SANDBOX_SSH_KEY` | SSH private key (full PEM content) | **NEW** |
| `SANDBOX_DATABASE_URL` | Full DB connection string for sandbox | **NEW** |
| `PROD_SSH_HOST` | IP/hostname of production server | May already exist |
| `PROD_SSH_USER` | SSH username on production server | May already exist |
| `PROD_SSH_KEY` | SSH private key for production server | May already exist |

### Frontend repo (new secrets to add)
| Secret Name | Value to set | Notes |
|-------------|-------------|-------|
| `VERCEL_TOKEN` | Vercel personal access token | **NEW** |
| `VERCEL_ORG_ID` | Vercel team/org ID | **NEW** |
| `VERCEL_PROJECT_ID` | Vercel project ID | **NEW** |
| `NEXT_PUBLIC_API_URL_SANDBOX` | `https://sandbox.enginchantier.ma` | **NEW** |
| `NEXT_PUBLIC_API_URL_PROD` | `https://api.enginchantier.ma` | Rename existing if needed |

---

## 6. GitHub Environments to Create

In each repo: Settings → Environments

### `sandbox`
- No required reviewers
- No wait timer
- Auto-deploys on every push to `develop`

### `production`
- Required reviewers: DIMATRABO (add other approvers if needed)
- No wait timer (deploy immediately after approval)

---

## 7. Assumptions (Architect must verify)

- [x] A1: Backend and frontend are in **separate** GitHub repos — CONFIRMED 2026-04-17
- [x] A2: No separate sandbox server — **sandbox and production share this same VPS** — CONFIRMED 2026-04-17
- [x] A3: Sandbox DB does not exist yet — **must be created** (new container or new DB in existing Postgres) — CONFIRMED 2026-04-17
- [ ] A4: Current backend uses `docker-compose` for deployment (likely, Architect to verify)
- [ ] A5: Frontend is Next.js (suspected from `/en/` i18n routing)
- [ ] A6: Docker Hub image for frontend = future option, not immediate requirement
- [x] A7: Current production deploy = **GitHub Actions** — CONFIRMED 2026-04-17

**Confirmed infra note (2026-04-17):**
- Everything runs on one VPS. Sandbox = a second set of Docker containers on the same host.
- `SANDBOX_SSH_HOST` = `PROD_SSH_HOST` (same machine, same IP).
- User plans to migrate sandbox to a separate server later if project gains traction. Design must not assume server separation but should not make it hard to split later.
- Sandbox DB: Architect to decide — new Postgres container (cleanest isolation) vs new database inside existing Postgres instance (simpler). Recommend new container.
- Risk: a runaway sandbox container could consume CPU/RAM and degrade production. Architect must specify Docker resource limits (`mem_limit`, `cpus`) on sandbox containers.

---

## 8. Implementation Phases

### Phase 1 — Architect: Repo Audit & Pipeline Design

**Repos (confirmed by user 2026-04-17):**
- Backend: https://github.com/DIMATRABO/enginchantier
- Frontend: https://github.com/DIMATRABO/engin.ma_front

**Tasks:**
- Clone/read both repos: find existing `.github/workflows/`, `docker-compose.yml`, `Dockerfile`, `package.json` / framework detection
- Verify A4 (docker-compose in use?) and A5 (Next.js?)
- Design exact YAML for `backend-sandbox.yml` and `backend-production.yml`
- Design sandbox `docker-compose.sandbox.yml` with separate network, ports, resource limits
- Specify Postgres sandbox container setup (port 5433, separate volume)
- Design frontend pipeline (Vercel environments or GitHub Actions + Vercel CLI)
- Specify all secrets needed per repo
- Output: `tasks/artifacts/strategy/cicd-architect-design.md` — ready for Developer to implement

### Phase 2 — Developer: Backend Workflows
- Implement `backend-sandbox.yml`
- Implement `backend-production.yml` with GitHub Environment gate
- Create GitHub Environments (`sandbox`, `production`) via API or guide user through UI
- Provide exact `.env.sandbox` template

### Phase 3 — Developer: Frontend Workflows
- Configure Vercel project environment variables per env
- Implement frontend pipeline (Vercel CLI via Actions OR native Vercel Git integration)
- Provide exact secrets list for Vercel

### Phase 4 — User: Secret Rotation (estimated 30 min)
- User adds all new secrets from §5 in GitHub
- First sandbox deploy test
- First production approval gate test

---

## 9. Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Sandbox server not provisioned | Blocker | Clarify with user before Phase 2 |
| Sandbox DB shares production server | High | Ensure schema/credential isolation |
| Vercel auto-deploy conflicts during migration | Medium | Disable Vercel Git integration temporarily |
| Production secrets reachable from sandbox workflow | Medium | GitHub Environments keep them isolated |

---

## 10. Success Criteria

- [ ] Push to `develop` → sandbox live within 5 min, zero prod impact
- [ ] Push to `main` → GitHub shows "Waiting for review" button
- [ ] Click approve → production updated within 5 min
- [ ] Frontend shows sandbox API URL in preview, prod URL in production
- [ ] Zero manual SSH needed for any deployment
