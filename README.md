# SDMS — Secure Digital Document Management System

Prototype for **PS 26190** (MHA · NCRB): storage, integrity proof, access control, search and audit for legal and
investigation documents. It runs on one machine with **no cloud account and no external API**:

* **PostgreSQL** — users, cases, document records, the hash-chained audit log
* **MongoDB** — encrypted document blobs (GridFS), sealed OCR text / entities / summaries, embeddings
* **Hyperledger Fabric 2.5** — the integrity ledger (2 organisations, both must endorse), reached through a small REST gateway
* **A local AI service** — OCR (Tesseract), a fine-tuned document classifier, multilingual embeddings, and an Ollama LLM for summaries — see [ai/README.md](ai/README.md)
* **nginx** — TLS 1.3 front door; React + TypeScript UI; FastAPI backend

Read [Limitations](#limitations-read-before-relying-on-this) and [what is not built](#not-built) before quoting any claim
about this project.

### Contents

[What works](#what-works) · [Architecture](#architecture) · [Getting the code](#getting-the-code) · [Run it](#run-it) ·
[Demo accounts](#demo-accounts) · [Try the integrity claim](#try-the-integrity-claim-yourself) ·
[Who can do what](#who-can-do-what) · [API](#api) · [Configuration](#configuration) · [Tests](#tests) ·
[Limitations](#limitations-read-before-relying-on-this) · [Not built](#not-built) · [Layout](#layout)

## What works

| Capability | Status | Notes |
|---|---|---|
| Auth, RBAC (officer / station admin / auditor), mandatory TOTP MFA | ✅ | lockout, forced first-login password change, TOTP replay protection, sessions revoked on logout / disable / password change, per-IP rate limiting, 8 h absolute session cap with sliding refresh |
| Case-tagged upload, versioning | ✅ | PDF, TXT, PNG, JPG, TIFF, DOCX; extension **and** magic bytes checked; 25 MB cap; every new version is a new anchored record |
| Encryption at rest | ✅ | AES-256-GCM, per-file key wrapped by a master key; OCR text, entities and summaries are sealed too |
| Integrity proof on Hyperledger Fabric | ✅ | SHA-256 + metadata anchored per version; verify re-hashes the decrypted file and checks the Fabric record; block hashes and links re-verified independently |
| Tamper-evident audit log | ✅ | hash chain in PostgreSQL, head anchored on Fabric every 5 min and on demand |
| Search | ✅ | filters + whole-word search over **encrypted** OCR text (blind index) + semantic search (embeddings), always limited to the caller's cases |
| Local AI | ✅ / ⚠️ | OCR incl. Hindi/Tamil packs, entity extraction, fine-tuned classifier (round 2, 81–99 % on held-out sets), summaries with a grounding guard. **Never evaluated on a real police document** — numbers in [ai/README.md](ai/README.md#how-good-is-the-classifier) |
| One-command deployment | ✅ | `docker compose up -d --build` → `https://localhost:8443` (TLS 1.3 only). Built and run end-to-end on Windows / Docker Desktop |
| Optional antivirus on upload | ⚠️ | ClamAV hook exists; tested against a fake `clamd` only — never a real ClamAV |

**Verified how:** the automated test-suite (below) and a scripted run against the Docker stack through the TLS front door:
enrol MFA → create case → upload a scanned PDF → OCR / entities / classification → anchored on Fabric (block number and tx id
returned) → verify (officer and auditor) → download → keyword + semantic search → LLM summary → audit chain and Fabric chain
verify → `down` / `up` with data kept → everything still verifies. TLS 1.2 is refused; HTTP redirects to HTTPS.

## Architecture

```
 browser ──TLS 1.3──► nginx ─► React app
                        └────► /api ─► FastAPI backend ──► PostgreSQL   users, cases, versions, audit chain
                                          │        ├──────► MongoDB      ciphertext (GridFS), sealed text, embeddings
                                          │        ├──────► AI service   OCR → entities → classifier → embeddings ─► Ollama (host)
                                          │        └──────► ClamAV       optional
                                          └──► ledger gateway ─► Fabric: orderer · peer0.police · peer0.court · `anchor` chaincode
```

```
upload ─► validate ─► (antivirus) ─► AI (OCR, classify, entities, embedding)
       ─► SHA-256 ─► AES-256-GCM encrypt ─► GridFS ─► anchor {uid, version, case no., sha256, size, uploader, time, prev hash} on Fabric ─► tx id
       ─► Mongo (sealed text + blind-index tokens + embedding) ─► PostgreSQL row.  A failure at any step removes what the earlier steps wrote.
download / verify ─► decrypt (auth-tag check) ─► re-hash ─► compare with the PostgreSQL record AND the Fabric record
                     match: served · mismatch: HTTP 409 + TAMPER_DETECTED audit alert
every action ─► audit row = SHA-256(previous row hash ‖ this row); chain head anchored on Fabric
```

* **Encryption:** per-file random data key, wrapped by the master key; the storage key is bound as authenticated data, so a
  ciphertext copied over another version fails to decrypt. TOTP secrets and all searchable text are sealed the same way.
* **Search over encrypted text:** words are HMAC-tokenised with a key derived from the master key (a "blind index"), so
  the database can match whole words without holding the text. Hindi and Tamil are tokenised too.
* **Fabric:** channel `sdmschannel`, two orgs (police, court) that must both endorse, chaincode `anchor` running as its own
  container. The Python backend cannot speak Fabric's gRPC Gateway API, so a small Node REST gateway sits in front; the ledger
  explorer in the UI reads blocks from the peer and re-checks each block header hash.
* **Ledger contents:** hashes and minimal metadata only — never document content, filenames or names.
* **Audit chain** detects edited or deleted rows; deleting the *newest* rows can't be seen from the chain alone, which is why its
  head is anchored on Fabric and `verify` checks the anchored entry still exists unchanged.

## Getting the code

The fine-tuned classifier weights (`ai/models/classifier/model.safetensors`, ~520 MB) are tracked with **[Git
LFS](https://git-lfs.com)**, not committed directly (GitHub hard-rejects any file over 100 MB). This matters for how
you get a working copy:

* **`git clone` (recommended — gets everything, including the real model weights):**
  ```powershell
  git lfs install                      # once per machine, if you haven't used Git LFS before
  git clone https://github.com/Balavigneshcse/Secure_Digital_Document_Management_System.git
  cd Secure_Digital_Document_Management_System
  ```
  Without `git lfs install` first, the clone still succeeds, but `ai/models/classifier/model.safetensors` will be a
  tiny ~130-byte pointer file instead of the real weights, and the AI service will fail to load the classifier at
  startup. Run `git lfs pull` inside the clone to fix that if it happens.

* **GitHub's "Download ZIP" button:** ZIP downloads **do not include Git LFS content at all** — this is a GitHub
  limitation, not something a repo setting can fix. If you go this route, `ai/models/classifier/model.safetensors`
  will be missing/a pointer file. Two ways to get a fully working copy after unzipping:
  1. Run `git init && git remote add origin <repo-url> && git lfs install && git lfs pull` once inside the unzipped
     folder (needs `git` + `git-lfs` installed, no separate GitHub account setup required for a public repo), **or**
  2. Regenerate the classifier locally instead of downloading it — see `ai/README.md` → "Training offline"
     (`ai/training/train_classifier.py`, ~5 minutes on a GPU). The AI service also runs without a classifier at all,
     falling back to a simpler rule-based document-type guess (OCR, entities and summaries still work fully).

Either way, once you have a real working copy, continue below.

## Run it

### A. Everything in Docker (recommended)

Needs Docker Desktop (~6 GB RAM free) and, for AI summaries, [Ollama](https://ollama.com) running on the host.

```powershell
python deploy/gen_env.py --demo        # writes .env with fresh random secrets; --demo also creates the demo accounts
ollama pull qwen2.5:3b                 # once, for summaries
ollama create sentinel-legal -f ai/Modelfile
docker compose up -d --build           # first build downloads several GB; later starts take ~30 s
```

Open <https://localhost:8443> and accept the browser's self-signed-certificate warning (port 8080 redirects to it).

```powershell
docker compose down                    # stop, keep all data (documents, chain, users)
docker compose down -v                 # stop and DELETE all data, including the Fabric chain
```

Never lose `.env`: `SDMS_MASTER_KEY` decrypts every stored document. Leave `--demo` out for anything that is not a demo, then
create the first accounts with the CLI (below).

For a guided walkthrough once it's running (which accounts to use, what to click), see [demo/README.md](demo/README.md) —
it also has a recorded video, a full account/case spreadsheet, and ready-to-upload sample documents.

### B. Development (backend and frontend on the host)

Uses your own PostgreSQL and MongoDB; Fabric and the AI service still come from Docker.

1. `docker compose up -d ledger-gateway ai` (this also starts the Fabric peers/orderer; the gateway listens on `127.0.0.1:8088`, the AI on `127.0.0.1:9000`)
2. In PostgreSQL create a least-privilege role and database — **not** the `postgres` superuser:
   `CREATE ROLE sdms_app LOGIN PASSWORD '…' CREATEDB;` and `CREATE DATABASE sdms OWNER sdms_app;` (`CREATEDB` is needed only by the tests)
3. `copy backend\.env.example backend\.env`, fill in the database password and copy the two keys from the root `.env`
4. Backend and frontend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python dev.py            # http://127.0.0.1:8000, demo accounts on, /docs enabled

cd ..\frontend                         # second terminal
npm install
npm run dev                            # http://localhost:5173 (proxies /api to the backend)
```

### Demo accounts

Created only when `SDMS_SEED_DEMO=true` (`--demo`, and `dev.py`), all password `Demo@Pass1234`:

| Username | Role / rank | Station / district |
|---|---|---|
| `officer.demo`, `officer2.demo` | Investigating officer | Central (CPS) |
| `admin.demo` | Station admin | Central (CPS) |
| `auditor.demo` | Auditor | — |
| `sho.demo` | Officer, rank **station_head** — full content access to every CPS case | Central (CPS) |
| `sp.demo` | Officer, rank **superintendent** — full content access to every case at every station it oversees | oversees CPS + Northside |
| `forensic.demo`, `judge.demo` | Only cases explicitly shared with that account (forensic: read-only its own uploads; judge: full read) | — |
| `judge.krr.demo`, `judge.chn.demo` | Judge, rank **district_court** — full read on every case in their district, no sharing needed | Karur / Chennai |
| `judge.hc.demo` | Judge, rank **high_court** — full read, every case, every district | — |
| `forensic.krr.demo`, `forensic.chn.demo` | Forensic lab; only cases explicitly shared *from that district* | Karur / Chennai |

The seeded set above is small (2 stations, no district). A full district hierarchy (2 districts × 2 stations × 5 cases,
with a forensic lab and a district court judge per district, plus a high court judge) can be built with the same CLI —
see the commands below and `demo/SDMS_test_accounts_and_cases.xlsx`, which documents exactly such a set already built
and verified on this deployment.

On first sign-in each account shows a QR code and key: add it to an authenticator app and enter the 6-digit code. Every later
sign-in asks for a fresh code.

Without demo data there is deliberately no sign-up. A station admin can self-service only plain officer accounts (`POST
/api/users`) and promote/demote one between plain officer and `station_head` (`PATCH /api/users/{id}`). Every other account
type — admin, auditor, `superintendent`, forensic, judge — needs the operator CLI (Docker:
`docker compose exec backend python -m app.cli …`; the password is read from the hidden prompt, or from stdin when piped):

```powershell
python -m app.cli create-district --code KRR --name "Karur District"                          # optional grouping
python -m app.cli create-station --code CPS --name "Central Police Station" --district-code KRR  # --district-code is optional
python -m app.cli create-user --username jdoe --full-name "J Doe" --role admin --station-code CPS
python -m app.cli create-user --username audit1 --full-name "Auditor" --role auditor
python -m app.cli create-user --username sp1 --full-name "SP" --role officer --rank superintendent   # no --station-code needed
python -m app.cli oversee --username sp1 --station-code CPS     # repeat per station; grants station-wide content access
python -m app.cli create-user --username lab1 --full-name "Forensic Lab" --role forensic --district-code KRR   # required for forensic
python -m app.cli create-user --username judge1 --full-name "District Judge" --role judge --rank district_court --district-code KRR
python -m app.cli create-user --username judge2 --full-name "High Court" --role judge --rank high_court        # no district
python -m app.cli reset-mfa --username audit1     # lost phone; also revokes their sessions; audited as MFA_RESET
python -m app.cli unlock --username jdoe
```

New accounts must change the password and enrol an authenticator at first sign-in. A station admin can reset MFA for officers
(any rank) in their station; the CLI is the recovery path for admin, auditor, forensic and judge accounts. `--rank` takes
`station_head`/`superintendent` for `--role officer`, or `district_court`/`high_court` for `--role judge` — the CLI rejects
mismatches (e.g. `--role officer --rank high_court`).

**Sharing a case with a forensic or judge account:** an officer with content access to the case, or a station admin (who
doesn't need content access themselves), grants it — `POST /api/cases/{id}/shares {"user_id": ...}`, revoked with `DELETE
/api/cases/{id}/shares/{user_id}` — or through the "Shared with" card on the case page in the UI. There is no expiry yet;
remove access manually when the review is done. `GET /api/users/reviewers` (officer/admin) lists the forensic/judge accounts
available to share with, already filtered to forensic labs in the requester's own district (a cross-district attempt is
rejected server-side too, not just hidden in the picker). District-court and high-court judges need no share at all — their
reach follows their rank automatically.

**What a forensic lab can do with a shared case, specifically:** it can file a *new* document (its own findings/evidence
report — `POST /api/cases/{id}/documents`) but can open, download or verify only documents it uploaded itself; an officer's
existing FIR/investigation files stay invisible to it, not even their titles. It cannot add a new *version* to someone
else's document, correct a classification, or request an AI summary. Judges are not read-restricted this way: any case a
judge can see (shared, or via a court rank), they can read every document in.

## Try the integrity claim yourself

1. Sign in as `officer.demo`, create a case, file a document. Note its **SHA-256** and **ledger tx / block**.
2. **Verify integrity** → *Verified*.
3. Corrupt the stored ciphertext the way an attacker with database access would (flips one bit; irreversible):
   `Get-Content deploy\tamper_demo.py | docker compose exec -T backend python - 1 1` (document 1, version 1; in a native
   run: `cd backend; .venv\Scripts\python ..\deploy\tamper_demo.py 1 1`)
4. **Verify integrity** → *FAILED*; **Download** is refused (HTTP 409).
5. Sign in as `auditor.demo` → **Audit log** shows a `TAMPER_DETECTED` alert; **Verify audit chain** and **Integrity ledger →
   Verify full chain** confirm the logs and the Fabric chain themselves are intact.

## Who can do what

| | Officer | Station head | Superintendent | Station admin | Auditor | Forensic lab | Judge (plain / district / high court) |
|---|---|---|---|---|---|---|---|
| Register a case | ✅ (auto-assigned) | ✅ | ✅ | ✅ (assigns officers) | — | — | — |
| See a case | assigned | + own station | + overseen stations | own station (metadata only) | — | only cases shared with them | shared / + own district / + everywhere |
| List a case's documents | assigned cases | + own station | + overseen stations | **never** | **never** | shared cases, **own uploads only** | same scope as "See a case", **full list** |
| Open / download / verify a document | assigned cases | + own station | + overseen stations | **never** | pass/fail only, any document | shared cases, **own uploads only** | same scope, **every document** |
| Upload a new document | assigned cases | + own station | + overseen stations | — | — | shared cases (new documents only, not new versions of someone else's) | — |
| New version, AI summary, correct a classification | assigned cases | + own station | + overseen stations | — | — | — | — |
| Assign/unassign officers; set an officer's rank; manage officer accounts; reset officer MFA | — | — | — | own station | — | — | — |
| Grant/revoke a case share with a forensic/judge account | on cases they can see content of | ″ | ″ | ✅ (any case at their station, no content access needed) | — | — | — |
| Audit log, ledger explorer, export | — | — | — | — | ✅ | — | — |

"Station head"/"superintendent" (officer) and "district_court"/"high_court" (judge) are **ranks**, not separate roles
(`PATCH /api/users/{id}` for the two officer ranks; the CLI's `--rank` for every other combination). A superintendent's
stations come from `station_oversight` and a district court's district from the judge's own `district_id`, both granted
only by the CLI. Requests for a case/document a user may not access return **404** (not 403) so existence isn't disclosed,
and every denial is audited.

## API

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/login` · `mfa/setup` · `mfa/enable` · `mfa/verify` · `change-password` · `refresh` · `logout` · `GET /api/auth/me` |
| Users (admin) | `GET, POST /api/users` · `PATCH /api/users/{id}` (active + rank) · `POST …/reset-mfa` · `…/unlock` · `GET /api/users/reviewers` (officer/admin: lists forensic/judge accounts) |
| Cases | `GET, POST /api/cases` · `GET /api/cases/{id}` · `POST …/assignments` · `DELETE …/assignments/{user}` · `POST …/summary` (AI overview, officer) · `POST …/shares` · `DELETE …/shares/{user}` |
| Documents | `GET, POST /api/cases/{id}/documents` (officer always; forensic on a shared case, filtered to its own uploads) · `GET /api/documents/{id}`, `download`, `verify` (officer/judge full, forensic own-uploads-only) · `POST …/versions`, `…/summary`, `…/classification-feedback` (officer only) |
| Verify | `GET /api/documents/{id}/versions/{n}/verify` (officer, forensic, judge, auditor) |
| Search | `GET /api/search?q&case_number&fir_number&party&doc_type&date_from&date_to&semantic` |
| Audit (auditor) | `GET /api/audit` · `/verify` · `/export` · `POST /api/audit/anchor` |
| Ledger (auditor) | `GET /api/ledger/status` · `/blocks` · `/verify` · `/tx/{tx_id}` |
| Health (public) | `GET /api/health` → `{status, ai, ledger:{backend, reachable}}` and nothing else |

Interactive docs at `/docs` only when `SDMS_ENABLE_DOCS=true` (off by default). The AI service contract is in
[ai/AI_CONTRACT.md](ai/AI_CONTRACT.md).

## Configuration

`SDMS_*` environment variables, or `backend/.env` (native) / the root `.env` (Docker, written by `deploy/gen_env.py`).

| Variable | Default | Purpose |
|---|---|---|
| `SDMS_DATABASE_URL` | — | PostgreSQL URL (`postgresql+psycopg://…`); anything else is rejected |
| `SDMS_MONGO_URL`, `SDMS_MONGO_DB` | `mongodb://localhost:27017`, `sdms` | MongoDB |
| `SDMS_MASTER_KEY` | generated into `data/master.key` | Base64 of 32 bytes; wraps every file key. **Losing it makes documents unreadable.** Use a KMS/HSM for anything real |
| `SDMS_JWT_SECRET` | generated into `data/jwt.secret` | Session-token signing key |
| `SDMS_LEDGER_BACKEND` | `fabric` | `fabric`, or `memory` (tests only — not durable) |
| `SDMS_FABRIC_GATEWAY_URL` / `_KEY` | `http://127.0.0.1:8088` / — | Ledger gateway |
| `SDMS_AI_SERVICE_URL` / `_KEY` | unset / — | AI service. Unset → built-in rule engine (no OCR of scans, no embeddings, no summaries) |
| `SDMS_SEED_DEMO` | `false` | Create demo accounts if there are no users |
| `SDMS_ENABLE_DOCS` | `false` | Swagger UI / OpenAPI |
| `SDMS_CORS_ORIGINS` | `localhost:5173` | Comma-separated allowed origins |
| `SDMS_TRUSTED_PROXIES` | empty | CIDRs of reverse proxies whose `X-Forwarded-For` is believed. Empty = ignore the header (a client cannot spoof its IP) |
| `SDMS_RATE_LIMIT_ENABLED`, `SDMS_LOGIN_ATTEMPTS_PER_MINUTE`, `SDMS_UPLOAD_PER_MINUTE` | `true`, 10, 30 | Rate limits |
| `SDMS_SESSION_MAX_HOURS`, `SDMS_ACCESS_TOKEN_MINUTES` | 8, 30 | Session lifetime (sliding refresh, hard cap) |
| `SDMS_CLAMAV_HOST` / `_PORT` / `_REQUIRED` | unset | Scan uploads with ClamAV; `_REQUIRED=true` refuses uploads if the scanner is unreachable |
| `SDMS_MAX_UPLOAD_MB`, `SDMS_LOCKOUT_THRESHOLD`, `SDMS_LOCKOUT_MINUTES`, `SDMS_AUDIT_ANCHOR_INTERVAL_SECONDS` | 25, 5, 15, 300 | Limits and timers |

## Tests

```powershell
cd backend; .venv\Scripts\python -m pytest             # needs PostgreSQL + MongoDB running; see below
cd frontend; npm run build                              # strict TypeScript check + production build
cd ai; ..\backend\.venv\Scripts\python -m pytest        # entity + grounding unit tests (pure Python)
```

Last full run (2026-09-22, against the round-2 classifier): **122 backend tests passed, 0 skipped** (~2.7 min) with the
Docker stack's Fabric network and AI service answering, plus 11 AI unit tests and a clean frontend build. Each test builds
its own throwaway PostgreSQL and MongoDB database. Tests marked `fabric` need the Fabric network and tests marked `ai` need
the AI service (`SDMS_FABRIC_GATEWAY_*`, `SDMS_AI_SERVICE_*` set); without them they **skip** rather than fail. They cover
RBAC (rank-based station/multi-station officer access, district-court/high-court judge reach, forensic's shared-and-own-
uploads-only access, cross-district share rejection), encryption at rest, tamper detection, audit-chain forgery, concurrent
versioning, multi-store rollback, rate limiting and spoofed `X-Forwarded-For`, session refresh and its cap, the antivirus
path, blind-index and semantic search (incl. case descriptions), and the real Fabric network (including a restart) and real
AI service (scanned PDF, photo, embeddings).

**Upgrading an existing deployment** to the rank/sharing feature, then to the district/court feature: `station_oversight`,
`case_shares` and `districts` are created automatically on the next backend start, but new *columns* on already-existing
tables are not (this project uses `create_all()`, not a migration tool, so it only creates missing tables) — run once,
before starting the new backend, in this order (the second statement needs the `districts` table to already exist, so
restart the backend between them if going straight from the pre-rank version):
```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS rank VARCHAR(16) NOT NULL DEFAULT 'officer';
-- restart the backend once here so create_all() adds the new `districts` table, then:
ALTER TABLE stations ADD COLUMN IF NOT EXISTS district_id INTEGER REFERENCES districts(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS district_id INTEGER REFERENCES districts(id);
```

## Limitations (read before relying on this)

* **The Fabric network is a single-host demo of the mechanism.** Both "organisations" and the one Raft orderer run on your
  machine under one operator, with `cryptogen`-issued keys in a Docker volume. It proves *how* anchoring, endorsement and
  verification work; it does not give the independence a real police-court deployment would (separate operators, ≥3 orderers,
  a real CA, HSM-held keys).
* **Key custody:** the master key comes from configuration or a file next to the data. Anyone who owns the host can decrypt.
  There is no KMS/HSM integration.
* **Not everything is encrypted.** Document files, OCR text, entities and summaries are. Case titles, party names, FIR numbers,
  filenames and audit details sit in PostgreSQL in clear (so they are filterable), and embeddings sit in MongoDB in clear (they
  reveal topic, not text). Use disk / database encryption as well.
* **Blind-index search** matches whole words only (no substring or fuzzy matching) and, like any searchable encryption, leaks
  which stored documents share a word.
* **PostgreSQL, MongoDB and Fabric are not one transaction.** Failures are rolled back by compensation, but killing the process at
  the wrong instant can leave an unreachable blob or a ledger entry with no database row. They are harmless, but not cleaned up.
* **Case sharing (forensic/judge) has no expiry.** An officer or admin must remember to revoke it; nothing auto-expires it.
  Rank changes and share grants aren't rate-limited or capped, so a compromised admin/officer account could over-share.
* **Rate limiting is per backend process** (in memory). Several replicas would each count separately; put a shared limiter in front.
* **TLS uses a self-signed certificate** (browser warning). Mount your organisation's certificate for real use.
* **Antivirus** is off unless you run ClamAV, and that path has only been tested against a stand-in `clamd`.
* **Sessions** live in `sessionStorage` (mitigated by a strict CSP, but a script injection would still read them).
* **AI quality is limited** — see [ai/README.md](ai/README.md): the classifier (round 2) was fine-tuned on synthetic
  templates plus LLM-written documents and scores 81–99 % on the four held-out test sets we have (one of them, the
  LLM-written set, partly reflects style-familiarity with the same generator rather than pure generalisation — see the
  caveat in ai/README.md); it has **never been evaluated on a real police document**. The LLM is used as published (only
  its prompt is customised) and can still write an unverifiable soft claim; Hindi/Tamil OCR is untested on real scans;
  handwriting is not supported. Summaries are labelled as AI-written and on demand.
* **Not certified** against the IT Act §65B, DPDP Act 2023 or CERT-In requirements. Only tested on Windows 11 + Docker Desktop.

## Not built

Items in the solution document that this prototype does **not** implement: digital signatures / PKI / eSign and the
multi-level approval workflow · a **prosecutor** role (forensic-lab and judge roles now exist, with per-case sharing — see
[Who can do what](#who-can-do-what) — but sharing has **no expiry** yet, so "time-boxed" is only half done) · version diff
view · IT Act §65B certificate generation · Flutter mobile app · Aadhaar e-KYC · ELK log analytics · KMS / HSM key custody ·
MinIO/S3 (GridFS is used instead).

## Layout

```
backend/       FastAPI app (app/), tests, Dockerfile, dev.py, .env.example
frontend/      React + TypeScript (Vite) and the nginx config (TLS 1.3)
ai/            local AI service (app/), training and evaluation (training/), datasets (data/),
               fine-tuned classifier (models/classifier/, Git LFS), Modelfile, AI_CONTRACT.md
fabric/        Hyperledger Fabric network: config, scripts, chaincode/anchor, gateway/
deploy/        gen_env.py (secrets), tamper_demo.py
demo/          recorded walkthrough video, demo accounts spreadsheet, QR codes, sample
               documents to upload — start here for a guided tour; see demo/README.md
docker-compose.yml   the whole system
```
