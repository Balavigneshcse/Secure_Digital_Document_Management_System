# Practice cases (10, ready to register)

Ten fresh, unregistered demo cases you can register live in front of judges, one after another or picking any one.
Every name, place and number is fictional. Each folder has a plain-text **00_CASE_INFO.txt** with the exact values
to type into the "+ New case" form, and 2 ready-to-upload `.txt` documents that the real AI classifies correctly.

Passwords are all `Demo@Pass1234`; each login also needs the 6-digit code from that account's QR code in
`../qr-codes/`. Wait for a fresh code (about 30 s) if you sign in to the same account twice in a row.

| # | Folder | Case | Login as | Type |
|---|---|---|---|---|
| 01 | [01_shop_burglary_karur_town](./01_shop_burglary_karur_town/) | Shop burglary, Mill Road, Karur | officer.krr1.demo | burglary |
| 02 | [02_chit_fund_fraud_karur_rural](./02_chit_fund_fraud_karur_rural/) | Chit fund fraud, Pugalur | officer.krr2.demo | cheating |
| 03 | [03_hit_and_run_chennai_central](./03_hit_and_run_chennai_central/) | Hit and run, Anna Salai | officer.chn1.demo | accident |
| 04 | [04_counterfeit_seizure_chennai_north](./04_counterfeit_seizure_chennai_north/) | Counterfeit electronics seizure, Ritchie Street | officer.chn2.demo | counterfeit goods |
| 05 | [05_upi_fraud_central_demo](./05_upi_fraud_central_demo/) | UPI phishing fraud | officer.demo | cyber fraud |
| 06 | [06_domestic_violence_central_demo](./06_domestic_violence_central_demo/) | Domestic violence complaint | officer2.demo | domestic violence |
| 07 | [07_missing_person_northside](./07_missing_person_northside/) | Missing person, minor | officer3.demo | missing person |
| 08 | [08_property_dispute_assault_karur_town](./08_property_dispute_assault_karur_town/) | Assault over property boundary dispute | officer.krr1.demo | assault |
| 09 | [09_drug_seizure_chennai_central](./09_drug_seizure_chennai_central/) | Narcotics seizure, T. Nagar | officer.chn1.demo | narcotics |
| 10 | [10_cheque_bounce_karur_rural_closed](./10_cheque_bounce_karur_rural_closed/) | Cheque dishonour, business dispute (for verdict demo) | officer.krr2.demo | cheque dishonour |

## How to demo one case (about 2 minutes)

1. Open the case's `00_CASE_INFO.txt` and sign in as the officer it names.
2. Click **+ New case**, and copy the Title / FIR number / Type / Description fields across.
3. Click **+ Add party** once per row and fill in each name and role.
4. Click **Create case**.
5. Upload the two files in the folder, one at a time, leaving **Document type** on Auto-detect (AI) so the AI's
   classification, confidence and extracted people/sections/dates render live for the judges.
6. Click **Verify integrity** on the FIR to show it is anchored on Hyperledger Fabric.

## Extra features worth showing on any case

- **Share the case** with `forensic.krr.demo` / `forensic.chn.demo` / `forensic.demo` (whichever matches the
  officer's district) — the forensic lab can then upload its own report but never sees the officer's documents.
- **Judge access**: `judge.krr.demo` / `judge.chn.demo` (district court) automatically see every case in their own
  district with no share needed; `judge.hc.demo` (high court) sees every case, every district.
- **Record a verdict**: case 10 is written for this — after filing its two documents, sign in as `judge.krr.demo`
  and use **Record verdict** on the case page. This closes the case and cannot be undone for that case, so use
  case 10 for it, not one you still want open for other demos.
- **Tamper detection**: use `deploy/tamper_demo.py` on any uploaded document's ID exactly as in
  `../video-case/README.md` — it is irreversible for that one document, so do it last, on a case you are finished
  demoing.

## Notes

- These are separate from `../video-case/` (the case already used to record the video) and `../sample-documents/`
  (older single-file samples) — use whichever fits what you are doing.
- Registering all 10 takes about 20 minutes end to end; for a short demo, just pick 2 or 3 that show different
  document types and different districts.
