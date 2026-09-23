# Demo kit

Everything needed to give a live demo of SDMS without digging through the main README.

- **`video/sdms_full_flow_1080p.mp4`** — the main walkthrough (1920x1080, ~3 minutes, real human-speed pacing, no
  speed-ups): officer registers a case and files the FIR → forensic lab uploads its own report and is blocked from
  the officer's document → officer sees both documents, judge sees the whole case automatically → tampering is
  detected and the auditor independently confirms it. See "About the full-flow video" below.
- **`video/sdms_demo_captioned.mp4`** — the original ~52s recorded walkthrough with burned-in captions (MFA, AI
  classification, tamper detection, ledger/audit verification, Station Head/Superintendent rank access).
- **`video/sdms_demo.mp4`** — the same original recording with no captions, for voicing over in a video editor.
- **`video/captions.srt`** — the caption text for the original recording, as a standalone subtitle file.
- **`SDMS_test_accounts_and_cases.xlsx`** — every demo login (19 accounts) and every test case (28), across 4 sheets:
  Districts & Stations, Accounts, Cases, Roles & Permissions. Most cases have no document yet — that's on purpose,
  see below.
- **`sample-documents/`** — 6 ready-to-upload `.txt` files (one per document type: FIR, witness statement, charge
  sheet, medical report, forensic report, evidence memo), each already verified against the real AI service. Use
  these to fill in the empty cases above and check upload + AI classification actually works.
- **`qr-codes/`** — one QR code per account (`<username>.png`), encoding the same MFA key as the spreadsheet. Scan
  instead of typing a 32-character secret in front of an audience.

## About the full-flow video

`video/sdms_full_flow_1080p.mp4` is one continuous, unedited recording — a real browser (Playwright) driving the
actual running app, typed character-by-character with real reading pauses between steps, at natural human speed (no
cuts, no speed-ups). It's silent by design; voice over it live or narrate from the beats below. In order:

1. **`officer.krr1.demo`** logs in, registers a brand-new case (House break-in, Bharathi Nagar), and files the FIR —
   the AI classifies it (`fir`, 100% confidence) and extracts persons/dates/sections live.
2. **`forensic.krr.demo`** logs in after the officer shares the case with it. The case's Documents table is *empty*
   even though the FIR exists — forensic has case-level access but not to documents it didn't upload. It files its
   own forensic report, then a direct link to the officer's FIR document returns **Not found** (not "Forbidden" —
   the system doesn't even reveal the document exists to an account with no right to it).
3. **`officer.krr1.demo`** logs back in and now sees both documents. **`judge.krr.demo`** logs in and the case is
   already there — a district court judge sees every case in their district automatically, with no share at all.
4. **Tamper detection:** the officer's FIR reads "Verified" — then `deploy/tamper_demo.py` flips one bit of the
   *stored ciphertext* directly in the database (simulating an attacker with DB access, not an app user). The next
   **Verify integrity** fails: "possible tampering... written to the audit trail." **`auditor.demo`** — the
   system's independent supervisor role — then filters the audit log to this case, sees the `TAMPER_DETECTED` entry
   with the actor and timestamp, confirms **Verify audit chain** still reports the log itself intact, and
   independently re-checks the same document by ID: "Tampering detected" — without ever being shown its content.

The original short video below predates the district/court/forensic-upload feature and doesn't show it; the
full-flow video above is the current, complete story end to end.

## About the original short video

Recorded the same way (Playwright against the real app, not staged screenshots), but sped up: six short clips
concatenated, no microphone in this environment. The captions carry the narration for you to read aloud, or drop
`captions.srt` into a video editor and record your own voice over `sdms_demo.mp4`. Covers: MFA login → AI
classification + Fabric-anchored Verify → live tamper detection → audit trail + ledger verification → station-wide
(Station Head) and multi-station (Superintendent) rank access → read-only forensic/judge sharing. It predates the
district/court hierarchy and forensic uploads, which the full-flow video above covers instead.

## Districts, courts and the forensic upload flow

The org model has two levels below the police stations:

- **District** (Karur, Chennai) — groups 2 stations, has one forensic lab and one district court judge.
- **District Court** judge — automatically sees every case at every station in their district, no sharing needed.
- **High Court** judge — automatically sees every case, every district.
- **Forensic lab** — still needs an explicit per-case share (and only from a station in its *own* district — sharing
  across districts is rejected by the server, not just hidden in the UI) but can now **upload its own findings**
  to a shared case. It still cannot open the officer's existing documents — only what it uploaded itself.

Try it: log in as `officer.krr1.demo` and open **CR-2026-KRR1-0001** (already has a scanned FIR and a forensic
report). Log in as `forensic.krr.demo` — the same case shows only the forensic report, not the FIR. Log in as
`judge.krr.demo` — it sees this case and all 9 others in Karur, automatically, without ever being shared anything.
Log in as `judge.hc.demo` — it sees all 28 cases in the system, Karur and Chennai and the original CPS/NPS ones alike.

## Before you start

```bash
docker compose up -d          # from the project root; ~30s if already built
```

Open **https://localhost:8443** — accept the self-signed-certificate warning once. All passwords are `Demo@Pass1234`.

## A ~5 minute walkthrough

1. **Log in as `officer.demo`**, scan its QR code, enter the 6-digit code.
2. Open **CR-2026-CPS-0002** (Motorcycle theft) → show the uploaded FIR, its AI-detected type/confidence, extracted
   entities, and **Verify integrity** (passes, anchored on Hyperledger Fabric — show the block number).
3. **Tamper demo:** in a terminal, `Get-Content deploy\tamper_demo.py | docker compose exec -T backend python - 1 1`
   (flips one bit of the stored ciphertext — irreversible, so only run this on the demo data). Refresh, click
   **Verify integrity** again → now **FAILED**, and **Download** is refused.
4. **Log in as `auditor.demo`** → **Audit log** shows the `TAMPER_DETECTED` alert; **Verify audit chain** and
   **Integrity ledger → Verify full chain** confirm the logs and the Fabric chain themselves are still intact.
5. **Log in as `sho.demo`** (Station Head) → **Cases** shows *every* Central Station case, not just one officer's —
   the rank-based access story.
6. **Log in as `forensic.demo`** → **Cases** shows exactly one case (shared with it), read-only: no upload button, no
   "Add version". Log in as `forensic2.demo` to show it sees a *different* case — sharing is per-account, per-case.

Full account list, every case, and the complete permissions matrix are in the spreadsheet.

## Notes

- These credentials (including the MFA secrets) are for this **local, offline demo instance only** — nothing here is
  reachable outside your machine. Still, don't reuse `Demo@Pass1234` anywhere real, and think twice before publishing
  this folder in a public repo alongside real account secrets from elsewhere.
- If you tamper with a document per step 3, that change is permanent for that one document version. Everything else
  (cases, other documents, other accounts) is unaffected, and you can keep demoing normally afterwards.
- The full-flow video's case (**CR-2026-KRR1-0007**, "House break-in, Bharathi Nagar") is real data left in the demo
  instance, not deleted afterwards — its FIR (document 24) was tampered with on camera and will keep showing FAILED
  on Verify integrity, exactly as in the video, so you can show the same result live.
- **If a role you just added shows a blank page:** hard-refresh (Ctrl+Shift+R). This was a real bug — the app didn't
  tell your browser to re-fetch `index.html` after a rebuild, so a browser that had the app open from before could get
  stuck on stale code. Fixed in `frontend/nginx.conf`; new visits are unaffected.
- **Search** now matches a case's description too (it didn't before — a real gap, now fixed and covered by a test).
