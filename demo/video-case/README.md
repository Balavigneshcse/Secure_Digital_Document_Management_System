# Video case: chain snatching, Karur Town

A fresh case with its own files for recording the full-flow demo. All names, numbers and plates are fictional. Each
file was run through the real AI service: FIR, witness statement, forensic report and judgment all classify
correctly at 100% confidence.

| File | Who uploads it | AI should say |
|---|---|---|
| `1_FIR_chain_snatching.txt` | `officer.krr1.demo` | `fir` |
| `2_witness_statement_murugesan.txt` | `officer.krr1.demo` | `witness_statement` |
| `3_forensic_report_cctv_and_chain.txt` | `forensic.krr.demo` | `forensic_report` |
| `4_CCTV_kovai_road_cam2.mp4` | `officer.krr1.demo` (optional) | stored as `evidence_record`; not analysed by the AI — open it with **View** to play it in the page |
| `VERDICT_TEXT_for_judge.txt` | not uploaded: `judge.krr.demo` types it into the **Record verdict** form | (saved as `judgment`) |

## Case details to type in (officer, "New case")

| Field | Value |
|---|---|
| Title | Chain snatching, Kovai Road, Karur |
| FIR number | 0688/2026 |
| Type | Snatching |
| Description | Two men on a black motorcycle snatched a 6-sovereign gold chain from a 54-year-old woman opposite Karur Bus Stand on 22/09/2026 at about 18:55 hours. |
| Parties | Lakshmi Devi = complainant; Murugesan K = witness; Arun Kumar = accused |

## Recording order

Passwords are all `Demo@Pass1234`; the 6-digit code comes from that account's QR in `../qr-codes/`. Wait for a new
code (about 30 s) if you log in to the same account twice in a row.

1. **Officer** `officer.krr1.demo`: log in, show **Cases**, click **New case**, fill the table above, save.
   Open the case, upload `1_FIR_chain_snatching.txt` (type: auto-detect), and show the AI result (`fir`, 100%,
   people, sections, amount). Click **Verify integrity**: it passes and shows the Fabric block. Upload
   `2_witness_statement_murugesan.txt` too. Then **Share** the case with `forensic.krr.demo`.
2. **Forensic** `forensic.krr.demo`: open the case. The Documents list is empty even though the FIR exists. Upload
   `3_forensic_report_cctv_and_chain.txt`. Paste the direct link of the officer's FIR: it shows **Not found**.
3. **Officer** again: the case now lists FIR, witness statement and the forensic report.
4. **Judge** `judge.krr.demo`: the case is already in the list (no share). Open it, show the documents and details.
   Scroll to **Record verdict**: choose Convicted, paste the sentence and reasons from `VERDICT_TEXT_for_judge.txt`,
   tick the confirmation, and record it. The case status changes to **closed** and a Judgment document appears.
5. **Tamper**: get the FIR's document id from its page URL (`/documents/<id>`), then in PowerShell from the project root:
   ```powershell
   Get-Content deploy\tamper_demo.py | docker compose exec -T backend python - <id> 1
   ```
   Log in as the officer, open the FIR, click **Verify integrity**: **FAILED**, and Download is refused.
6. **Auditor** `auditor.demo`: **Audit log**, filter by the case number. Show `TAMPER_DETECTED` (who, when),
   `VERDICT_RECORDED` and the uploads. Click **Verify audit chain** (intact) and, under **Integrity ledger**,
   **Verify full chain**.

Run the tamper command only on this case's documents: it is irreversible. To record again, make a new case with a
different title and FIR number (for example 0689/2026).
