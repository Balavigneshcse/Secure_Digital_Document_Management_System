# Sample documents to upload

Six ready-to-use `.txt` files, one per document type, written to actually test the AI pipeline rather than just be
placeholders — each was run through the real classifier just now and got the answer shown, at 100% confidence:

| File | Should classify as |
|---|---|
| `1_fir_shop_burglary.txt` | `fir` |
| `2_witness_statement.txt` | `witness_statement` |
| `3_charge_sheet.txt` | `charge_sheet` |
| `4_medical_report.txt` | `medical_report` |
| `5_forensic_report.txt` | `forensic_report` |
| `6_evidence_seizure_memo.txt` | `evidence_record` |

## How to test

1. Log in as an officer (e.g. `officer.krr1.demo`) and open one of the empty cases in the spreadsheet's Cases
   sheet (marked "Upload your own file to test").
2. **File a document** → choose one of these `.txt` files → leave **Document type** as "Auto-detect (AI)".
3. After it's filed, open the document and check: the **AI suggestion** matches the table above, the **entities**
   (persons, sections, dates...) picked out the names and section numbers from the text, and **Verify integrity**
   passes with a real Fabric block number.
4. To test the *forensic* side of the flow: as an officer, share that same case with your district's forensic lab
   (the "Shared with" card on the case page), then log in as the lab (e.g. `forensic.krr.demo`) and upload
   `5_forensic_report.txt` as its own finding. Back as the officer, you'll see both documents; as the lab, only its
   own.

These are synthetic, written for this test - not real case records. Feel free to edit them or write your own; any
plain-text, PDF, PNG, JPG, TIFF or DOCX file under 25 MB works the same way.
