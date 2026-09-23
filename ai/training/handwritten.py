"""A small, hand-written test set: realistic documents written by a third "author" (neither the templates nor the local
LLM). Two or three per class, English plus a few Hindi. It is tiny - each document is ~3 percentage points - so use it as
a sanity check on the distribution gap, not as a precise accuracy figure.

    python -m training.handwritten data/handwritten_test.jsonl
"""
from __future__ import annotations

import json
import pathlib
import sys

DOCS: list[tuple[str, str]] = [
    ("fir", """Police Station Saket, New Delhi. FIR 0231/2026 dated 04.02.2026.
Complainant Ms Rina Kapoor states that her handbag containing a mobile phone and Rs 8,000 was snatched by two men on a motorcycle near Saket Metro Station at about 8:10 pm. Offence: Section 304 BNS. Case registered; investigation assigned to SI Anil Rathi."""),
    ("fir", """F.I.R. - Thana Sadar, Bhopal - Dt. 19-11-2025
Informant: Ganesh Prasad, s/o Ram Lal, r/o Barkheda.
Report: my buffalo was stolen from the cowshed last night and the lock was found broken. I suspect Kalu of the same village. Please register a case. u/s 379, 457 IPC.
Sd/- Ganesh Prasad (thumb impression)"""),
    ("fir", """प्रथम सूचना रिपोर्ट। थाना सिविल लाइन्स, जिला जबलपुर। शिकायतकर्ता अशोक यादव ने बताया कि दिनांक 02/03/2026 की रात उनकी दुकान का ताला तोड़कर नकदी और सामान चोरी कर लिया गया। धारा 331(4), 305 बीएनएस के तहत मामला दर्ज किया गया।"""),
    ("police_report", """Daily Diary Entry No. 88. PS Rajajinagar. 14/07/2025 21:40 hrs.
Sri Manjunath (Beat constable 2231) reports that a street-light dispute between two neighbours led to an argument; both were counselled and sent home. No injury and no complaint. Entry made for record."""),
    ("police_report", """To The SHO, Town Police Station, Madurai.
Subject: Request for police protection.
Respected Sir, I, K. Selvi, have been receiving abusive calls from an unknown number since 3 September and I fear for my safety. Kindly inquire and take necessary action. Call screenshots are attached.
Date 08.09.2025"""),
    ("police_report", """थाना गोमती नगर - रोजनामचा प्रविष्टि 57 - दिनांक 03/02/2026। श्रीमती सीमा पांडे ने सूचना दी कि उनके पड़ोसी द्वारा गली में कचरा फेंका जा रहा है। दोनों पक्षों को थाने बुलाकर समझाइश दी गई। कोई अपराध नहीं बनता।"""),
    ("investigation_record", """Case Diary - Part I. Cr. No. 512/2025, PS Vijayawada. Date 02.12.2025.
Visited the scene at Benz Circle and collected CCTV footage from two shops; DVR seized. Statement of the shop owner Mr. Raju recorded. Suspect identified from the footage. Notice issued to the telecom company for the call records of the number ending 4471.
Next: arrest of the suspect."""),
    ("investigation_record", """Scene of Crime Memo
The room on the second floor of Sri Krishna Lodge was examined on 21 March 2026. Bed sheet disturbed, a glass tumbler with residue on the table, suitcase open. The fingerprint expert lifted prints from the table and the door handle. Photographs from 14 angles were taken. Prepared in the presence of two independent witnesses."""),
    ("witness_statement", """I, Deepa Nair, aged 34, teacher, state that on 5 January I was returning from school at about 4 pm when I saw a white car hit a cyclist near Kalamassery junction. The driver got out, looked at the man, and drove away without helping. I noted the number KL 07 BK 2219.
Sd/- Deepa Nair. Recorded by SI P. Menon under Section 180 BNSS."""),
    ("witness_statement", """Q: What did you see?
A: I saw the accused hit my brother with an iron pipe.
Q: Where were you standing?
A: About 15 feet away near the tea stall.
Q: Did you know the accused before?
A: Yes, he has been our neighbour for many years.
-- Examination-in-chief of PW-3 continued."""),
    ("witness_statement", """मैं, राधा देवी, उम्र 45 वर्ष, निवासी ग्राम रामपुर, बयान करती हूँ कि दिनांक 10/01/2026 को मैंने अपने सामने आरोपी को महेश को लाठी से मारते देखा। मेरा बयान मुझे पढ़कर सुना दिया गया है, जो सही है।"""),
    ("charge_sheet", """Final Report under Section 193 BNSS. Crime No 90/2026, Police Station Cyber Crime, Hyderabad.
Accused: A1 Rakesh Goud (arrested), A2 unknown. Sections: 318(4), 319(2) BNS and 66D IT Act.
Investigation is concluded; the evidence includes bank transfers, IP logs and statements of 11 witnesses. The accused are charge-sheeted for trial."""),
    ("charge_sheet", """CHARGE SHEET No. 44/2025
The accused Suresh Mane is chargesheeted for offences under Sections 324 and 506 IPC.
List of witnesses: 1. the complainant, 2. Dr. Kulkarni (medical officer), 3. two eyewitnesses.
List of documents: FIR, MLC, spot panchnama, arrest memo.
Investigating Officer: PI Deshmukh."""),
    ("court_filing", """In the Court of the Sessions Judge, Patiala House.
Application for anticipatory bail under Section 482 BNSS on behalf of the applicant Neeraj Malik in FIR No. 118/2026.
It is submitted that the applicant has been falsely named, is a government servant with deep roots in society, and is willing to join the investigation. It is therefore prayed that the applicant be granted anticipatory bail."""),
    ("court_filing", """IN THE HIGH COURT OF KERALA AT ERNAKULAM
W.P.(Crl.) No. 1042/2026     Petitioner: Sajan Thomas
The petitioner seeks a direction to the respondent police to decide his complaint dated 12.01.2026. Counsel for the petitioner submits that no action has been taken despite reminders.
Reliefs prayed: a writ of mandamus."""),
    ("evidence_record", """Seizure Memorandum
On 03/08/2025 at 6:15 pm, at the residence of the accused Vinod Sahu, the following were seized in the presence of panch witnesses: 1) Vivo mobile, IMEI ending 8842; 2) Rs 1,20,000 in cash bundle; 3) one notebook with entries. The articles were sealed with the seal of PS Kotwali and the signatures of the panchas were obtained."""),
    ("evidence_record", """Exhibit Register - Court of ACJM Nashik. S.C. 71/2024.
Ex-3: blood stained shirt (sealed packet no. 4).
Ex-4: weapon (axe), sealed packet no. 5.
Ex-5: photographs of the scene.
Received from the Malkhana on 12.02.2026. Seals found intact when opened in court."""),
    ("forensic_report", """State Forensic Science Laboratory - Report No. FSL/B/2026/1187.
Exhibits: 1 (viscera) and 2 (stomach contents), received in sealed jars. Analysis by thin layer chromatography and GC-MS.
Result: an organophosphate pesticide (chlorpyrifos) was detected in Exhibits 1 and 2.
Opinion: the viscera contain chlorpyrifos."""),
    ("forensic_report", """Cyber Forensic Report
Device: Lenovo laptop. The disk was imaged using a write-blocker and the SHA-256 hash was verified. 240 deleted image files were recovered, and the browser history shows access to the fraudulent payment site on 14 Feb 2026. Findings are in the annexed tables.
Examiner: Dr. S. Iyer"""),
    ("legal_notice", """LEGAL NOTICE
Under instructions of my client M/s Vikas Traders. You purchased goods worth Rs 2,45,000 on credit and issued cheque no. 004512, which was dishonoured. You are called upon to pay within 15 days, failing which proceedings under Section 138 of the NI Act will be initiated.
Adv. R. Bansal"""),
    ("legal_notice", """Notice to appear - Section 35(3) BNSS
To Mr. Arvind Shetty. In connection with Crime No. 233/2026 you are required to appear before the undersigned at Kadri Police Station on 18 April 2026 at 11 am with your identity documents. Non-compliance may lead to arrest.
SI Naveen Kumar"""),
    ("judgment", """IN THE COURT OF THE ADDITIONAL DISTRICT AND SESSIONS JUDGE, GURUGRAM
JUDGMENT
The accused was tried for offences under Sections 376 and 506 IPC. The prosecution examined 9 witnesses. The testimony of the victim was found reliable and is corroborated by the medical evidence. The accused is held guilty and convicted; to be heard on the question of sentence on 22.07.2025."""),
    ("judgment", """ORDER
The application for bail filed by the accused Imran Sheikh was heard. Considering that the charge sheet is filed and the custody has exceeded 14 months, the accused is released on bail on furnishing a bond of Rs 50,000 with one surety. He shall attend the court on every date. Application allowed."""),
    ("medical_report", """MLC No 4418/26. Name: Sunil Patil, 27 M. Brought by police with an alleged history of assault.
Injuries: 1) lacerated wound 3 cm over the right eyebrow; 2) contusion over the left cheek. X-ray skull: no fracture.
Injuries are simple in nature, duration about 6 hours.
Dr. A. Mehta, CMO"""),
    ("medical_report", """Post Mortem Report
Body of an adult male, approx. 40 years, identified by his brother. A ligature mark is noted around the neck; hyoid bone intact. Cause of death: asphyxia due to hanging (ante-mortem). Time since death 12-18 hours. Viscera preserved.
Autopsy done by Dr. Fernandes on 09/05/2026."""),
    ("arrest_warrant", """WARRANT OF ARREST
To the Officer In-charge, Kondapur Police Station.
Whereas Anil Reddy, accused in CC No. 1121/2025, has failed to appear on repeated dates, you are directed to arrest him and produce him before this court on 30 June 2026. Issued under the seal of the court.
Judicial Magistrate First Class, Ranga Reddy"""),
    ("arrest_warrant", """Non-bailable warrant issued against the accused in Sessions Case 15/2024 for non-appearance. The Superintendent of Police is directed to execute the warrant, and a report is to be submitted on the next hearing date. A copy is sent to the DCP for compliance."""),
    ("other", """Dear Team,
Reminder: the quarterly review meeting is scheduled for Friday at 3 pm in Conference Room B. Please share your slides by Thursday evening. Also, the cafeteria will be closed for renovation next week.
Regards, HR"""),
    ("other", """INVOICE No 2231
Customer: Priya Stores
Items: rice 25 kg x 4, sugar 10 kg x 2, oil 5 L x 3
Total: Rs 6,420. Payment received by UPI on 10/03/2026. Thank you for your business."""),
]


def write(path: str) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for label, text in DOCS:
            lang = "hi" if any("ऀ" <= ch <= "ॿ" for ch in text) else "en"
            f.write(json.dumps({"text": text, "label": label, "lang": lang, "variant": -2, "source": "handwritten"}, ensure_ascii=False) + "\n")
    print(f"wrote {len(DOCS)} documents to {p}")


if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else "data/handwritten_test.jsonl")
