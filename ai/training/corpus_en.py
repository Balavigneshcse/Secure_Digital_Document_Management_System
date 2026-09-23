"""English synthetic documents. Each class has several structurally different layouts; `corpus.py` holds the
last layout of every class out of training so validation measures generalisation to unseen formats."""
from __future__ import annotations

from .pools import COURTS, HIGH_COURTS, INJURIES, ITEMS, BANKS, FSL_TESTS, OCCUPATIONS, R


def _case_hdr(r: R) -> dict:
    off = r.offence()
    return dict(off=off, ps=r.station(), dist=r.district(), fir_no=f"{r.number(1, 999):03d}/{r.year()}", d=r.date(),
                sec=r.sections(off), comp=r.title_name(), acc=r.title_name(False), place=r.place(), t=r.time())


# ------------------------------------------------------------------------------------------------- FIR
def fir_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""FIRST INFORMATION REPORT
(Under Section 154 Cr.P.C.)
1. District: {c['dist']}   P.S.: {c['ps']}   Year: {c['fir_no'][-4:]}   FIR No.: {c['fir_no']}   Date: {c['d']}
2. Acts & Sections: {c['sec']}
3. (a) Occurrence of offence: Date {r.date()} Time {c['t']}
   (b) Information received at P.S.: Date {c['d']} Time {r.time()}
4. Type of information: Written
5. Place of occurrence: {c['place']}, about {r.number(1, 12)} km from the police station
6. Complainant / Informant: {c['comp']}, aged {r.number(20, 70)} years, {r.choice(OCCUPATIONS)}, mobile {r.phone()}
7. Details of known / suspected accused: {c['acc']}
8. Properties stolen / involved: {r.choice(ITEMS)} valued at {r.amount()}
9. FIR contents: Sir, I {c['comp'].split()[-1]} respectfully state that on {r.date()} at about {c['t']} the accused {c['off']['act']} at {c['place']}. I request that legal action may be taken.
10. Action taken: Since the above report reveals commission of offence under {c['sec']}, the case is registered and investigation is taken up by {r.rank_name()}.
Signature of Officer in charge, Police Station {c['ps']}
"""


def fir_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""FIRST INFORMATION REPORT (Under Section 173 BNSS, 2023)
Police Station: {c['ps']}, {c['dist']}    FIR No. {c['fir_no']}    Date and time of registration: {c['d']}, {c['t']}
Offence(s): {c['off']['en']} - {c['sec']}
Informant: {c['comp']}, resident of {c['place']}
Brief facts: The informant reported that on {r.date()} the accused {c['acc']} {c['off']['act']}. The informant identified the accused. The informant produced {r.choice(ITEMS)}.
Registered by: {r.rank_name()}. A copy of this FIR has been sent to the Hon'ble Magistrate and given to the informant free of cost.
"""


def fir_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""F.I.R. No. {c['fir_no']}   P.S. {c['ps']}   Dist. {c['dist']}
Information given by: {c['comp']} S/o {r.name(False)}, r/o {c['place']}
Date of report: {c['d']}
That on the night of {r.date()}, unknown persons {c['off']['act']}. The complainant came to know about the incident in the morning and reports the matter. Registered u/s {c['sec']}. Investigation entrusted to {r.rank_name()}.
Complainant's signature / thumb impression
"""


def fir_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""Police Station: {c['ps']} | FIR: {c['fir_no']} | Registered on {c['d']}
Complaint recorded from {c['comp']} ({r.choice(OCCUPATIONS)}), phone {r.phone()}:
"I am living at {c['place']}. On {r.date()}, around {c['t']}, {c['acc']} {c['off']['act']}. Please register a case and arrest the accused."
Case registered under {c['sec']}. Copy forwarded to the court. First Information Report read over to the informant and admitted correct.
"""


# ------------------------------------------------------------------------------------------ police report
def pr_0(r: R) -> str:
    ps = r.station()
    return f"""GENERAL DIARY (DAILY DIARY) - POLICE STATION {ps.upper()}
GD Entry No. {r.number(1, 400)}    Date: {r.date()}    Time: {r.time()}
Complaint received from {r.title_name()}, resident of {r.place()}, regarding a dispute with a neighbour over a boundary wall. The matter was marked to {r.rank_name()} for enquiry. No cognizable offence was disclosed at this stage; both parties were counselled and asked to appear on {r.date()}.
Duty officer: {r.rank_name()}
"""


def pr_1(r: R) -> str:
    return f"""POLICE REPORT - PRELIMINARY INQUIRY
Police Station {r.station()}, District {r.district()}
Subject: Missing person {r.name()}, aged {r.number(8, 70)} years
It is submitted that on {r.date()} {r.title_name()} reported that the above named person has been missing since {r.date()}. Enquiries were made at relatives' houses, hospitals and the bus stand. Photographs and description have been circulated to all police stations. A missing person report (GD No. {r.number(1, 400)}) has been entered. Further inquiry is in progress.
{r.rank_name()}
"""


def pr_2(r: R) -> str:
    ps = r.station()
    return f"""To,
The Station House Officer,
Police Station {ps}, {r.district()}
Subject: Complaint regarding harassment and threats
Sir, I {r.name()}, resident of {r.place()}, most respectfully submit that since {r.date()} a person named {r.name(False)} has been threatening me over the phone ({r.phone()}). I request you to kindly inquire into the matter and take necessary action.
Date: {r.date()}                                                            Yours faithfully
Received at the police station, GD No. {r.number(1, 400)}
"""


def pr_3(r: R) -> str:  # held out
    return f"""BEAT OFFICER'S REPORT
Beat No. {r.number(1, 20)}, P.S. {r.station()}    Date: {r.date()}
During patrolling on the night of {r.date()} between {r.time()} and {r.time()} the undersigned noticed a suspicious vehicle {r.vehicle()} parked near {r.choice(['the market', 'the railway crossing', 'the bus stand'])}. The driver could not explain his presence. He was questioned and released after verification. Nothing objectionable was found. Reported for information of the SHO.
{r.rank_name()}
"""


# ----------------------------------------------------------------------------------- investigation record
def inv_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""CASE DIARY (Section 172 Cr.P.C.)
Case Diary No. {r.number(1, 40)}    FIR No. {c['fir_no']}    P.S. {c['ps']}    Date: {c['d']}
Investigation conducted today by {r.rank_name()}:
1. Visited the place of occurrence at {c['place']} and inspected the spot; prepared rough site plan.
2. Examined {r.title_name()} and {r.title_name()} and recorded their statements under Section 161.
3. Requested the CCTV footage from the nearby shop; the footage has been secured.
4. Collected call detail records of the suspected mobile number {r.phone()}.
5. Searched for the accused {c['acc']} at his residence; he was not found.
Next steps: to send the seized articles to the forensic laboratory and to seek police custody of the accused after arrest.
"""


def inv_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""SPOT INSPECTION MEMO / PANCHNAMA
Case FIR No. {c['fir_no']}, P.S. {c['ps']}
Prepared at {c['place']} on {c['d']} between {r.time()} and {r.time()} in the presence of panch witnesses {r.title_name()} and {r.title_name()}.
The spot was inspected. The lock of the front door was found broken. Foot marks were noticed near the rear wall. A crowbar was found lying at a distance of {r.number(2, 15)} metres. Photographs and video of the spot were taken. The panchnama was read over to the panch witnesses who signed it in token of correctness.
Investigating officer: {r.rank_name()}
"""


def inv_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""INVESTIGATION PROGRESS REPORT
To: The Deputy Commissioner of Police, {c['dist']}
Sub: Status of Crime No. {c['fir_no']} of P.S. {c['ps']} u/s {c['sec']}
Status as on {r.date()}: The complainant and {r.number(2, 6)} witnesses have been examined. The accused has been identified as {c['acc']}. Notice under Section 41A was served. The exhibits are pending examination at the laboratory. Bank statements have been requisitioned. The investigation is expected to be completed within {r.number(10, 45)} days.
{r.rank_name()}, Investigating Officer
"""


def inv_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""Investigation notes of the IO - Crime {c['fir_no']}
{c['d']}: Recorded statement of the complainant. Verified the version with the neighbours.
{r.date()}: Traced the suspect through mobile location data. Interrogated {c['acc']}, who disclosed the place where {r.choice(ITEMS)} was hidden.
{r.date()}: Recovered the articles at the instance of the accused in the presence of independent witnesses. Prepared the recovery memo. Accused arrested. Sent the exhibits for examination.
"""


# ------------------------------------------------------------------------------------- witness statement
def ws_0(r: R) -> str:
    c = _case_hdr(r)
    w = r.name()
    return f"""STATEMENT OF WITNESS (Under Section 161 Cr.P.C.)
FIR No. {c['fir_no']}, P.S. {c['ps']}, Dist. {c['dist']}
I, {w}, aged {r.number(18, 75)} years, {r.choice(OCCUPATIONS)}, resident of {c['place']}, state as under:
On {r.date()} at about {c['t']} I was present near {r.choice(['my shop', 'the bus stop', 'my house'])} when I saw {c['acc']} {c['off']['act']}. I know the accused person for the last {r.number(2, 12)} years and I can identify him if produced before me. I raised an alarm and the neighbours gathered. I have not told this to anyone else.
The statement has been read over to me and is correct.
Signature of the witness                                Recorded by {r.rank_name()}
"""


def ws_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""STATEMENT UNDER SECTION 164 Cr.P.C.
Before the {r.choice(COURTS)}, {c['dist']}
Statement of {r.name(True)}, aged {r.number(10, 40)} years, recorded on {c['d']}
After being explained that she is not bound to make a statement and that it may be used as evidence, and after being satisfied that she is making it voluntarily, the witness stated: "On {r.date()} the accused {c['acc']} {c['off']['act']} at {c['place']}. I am telling this without any pressure or inducement."
Certificate of the Magistrate: I have explained to the witness that she is not bound to make a confession and I believe that this statement was voluntarily made.
"""


def ws_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""Statement of eyewitness in Crime No. {c['fir_no']}, P.S. {c['ps']}
Q1. Please state your name and address.
A1. My name is {r.name()}, and I live at {c['place']}.
Q2. Where were you on the date of the incident?
A2. On {r.date()} I was at my workplace until evening and while returning I saw the incident.
Q3. Whom did you see?
A3. I saw {c['acc']} running from the spot.
Q4. Can you identify the person?
A4. Yes, I can identify him.
Statement recorded by {r.rank_name()} and read over to the witness.
"""


def ws_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""IN THE COURT OF THE {r.choice(COURTS).upper()}
State vs {c['acc']}            Sessions Case No. {r.number(1, 400)}/{r.year()}
DEPOSITION OF PW-{r.number(1, 9)}
{r.name()}, aged {r.number(20, 70)} years, examined on oath on {r.date()}.
Examination-in-chief by the Public Prosecutor: I am a resident of {c['place']}. On the day of the incident I saw the accused present in the court {c['off']['act']}. I gave my statement to the police.
Cross-examination by the defence counsel: It is incorrect that I have a dispute with the accused. It is incorrect that I am deposing falsely.
"""


# --------------------------------------------------------------------------------------------- charge sheet
def cs_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""FINAL REPORT / CHARGE SHEET
(Under Section 173(2) Cr.P.C.)
In the Court of the {r.choice(COURTS)}, {c['dist']}
1. District: {c['dist']}   P.S.: {c['ps']}   FIR No.: {c['fir_no']}   Date: {c['d']}
2. Final Report / Charge Sheet No.: {r.number(1, 200)}/{r.year()}   Date: {r.date()}
3. Acts and Sections: {c['sec']}
4. Type of Final Report: Charge sheeted
5. Name of the Investigating Officer: {r.rank_name()}
6. Name of the complainant: {c['comp']}
7. Details of accused persons charge-sheeted: {c['acc']}, aged {r.number(20, 55)} years, resident of {c['place']}; status: {r.choice(['in judicial custody', 'on bail', 'absconding'])}
8. List of witnesses: {r.title_name()}, {r.title_name()}, {r.title_name()}, {r.rank_name()}
9. List of documents and material objects relied upon: FIR, seizure memo, site plan, {r.choice(['FSL report', 'medical report', 'call detail records'])}
10. Conclusion: The investigation has disclosed sufficient evidence against the accused to send him up for trial.
"""


def cs_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""CHARGE SHEET NO. {r.number(1, 200)}/{r.year()}
State versus {c['acc']}
P.S. {c['ps']}, Crime No. {c['fir_no']}
Charge: That on or about {r.date()} at {c['place']} the accused {c['off']['act']} and thereby committed an offence punishable under {c['sec']}.
Evidence collected: statements of {r.number(3, 9)} witnesses, recovery of {r.choice(ITEMS)}, {r.choice(['expert opinion', 'medical evidence', 'electronic evidence'])}.
Prayer: It is therefore prayed that the accused may be summoned and tried in accordance with law.
Submitted by {r.rank_name()}, Investigating Officer
"""


def cs_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""POLICE REPORT UNDER SECTION 193(3) BNSS - CHARGE SHEET
Station: {c['ps']}   Case No.: {c['fir_no']}   Court: {r.choice(COURTS)}
Accused (A-1): {c['acc']}, S/o {r.name(False)}, r/o {c['place']}
Sections invoked: {c['sec']}
Brief facts of the case: The complainant {c['comp']} lodged a report that the accused {c['off']['act']}. During investigation the allegation was found to be true and the accused was arrested on {r.date()}.
Witnesses to be examined at trial: PW-1 to PW-{r.number(5, 12)}. Documents enclosed: {r.number(6, 25)} pages.
The accused is forwarded to face trial.
"""


def cs_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""IN THE COURT OF THE {r.choice(COURTS).upper()}
Charge-sheet submitted by the police in Case Crime No. {c['fir_no']} of P.S. {c['ps']}
Accused named in column 11: {c['acc']} (arrested {r.date()}), {r.name(False)} (absconding, proceedings under Section 82 requested)
The final report after completion of investigation is filed with the list of prosecution witnesses and the list of seized property. Offences made out: {c['sec']}. Further investigation is reserved regarding the absconding accused.
"""


# -------------------------------------------------------------------------------------------- court filing
def cf_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""IN THE COURT OF THE {r.choice(COURTS).upper()}, {c['dist'].upper()}
BAIL APPLICATION No. {r.number(1, 900)}/{r.year()}
State vs {c['acc']}      FIR No. {c['fir_no']}, P.S. {c['ps']}, u/s {c['sec']}
Application under Section 439 Cr.P.C. on behalf of the applicant / accused for grant of regular bail
MOST RESPECTFULLY SHOWETH:
1. That the applicant has been falsely implicated in the present case and is in judicial custody since {r.date()}.
2. That the applicant is a permanent resident of {c['place']} and there is no likelihood of his absconding or tampering with the evidence.
3. That the investigation is complete and the charge sheet has been filed.
PRAYER: It is therefore most humbly prayed that the applicant may kindly be released on bail on such terms as this Hon'ble Court may deem fit.
Place: {c['dist']}    Date: {r.date()}                                  Through counsel {r.title_name()}, Advocate
"""


def cf_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""IN THE HIGH COURT OF {r.choice(HIGH_COURTS).upper()}
CRIMINAL WRIT PETITION No. {r.number(1, 9000)} of {r.year()}
MEMO OF PARTIES
{c['acc']}, aged {r.number(20, 60)} years, resident of {c['place']} ... Petitioner
Versus
1. State through the Secretary, Home Department  2. Superintendent of Police, {c['dist']} ... Respondents
WRIT PETITION under Article 226 of the Constitution of India praying for quashing of FIR No. {c['fir_no']} registered at P.S. {c['ps']}
The petitioner above named respectfully submits: that the allegations made in the impugned FIR are false and motivated. It is therefore prayed that this Hon'ble Court may be pleased to issue a writ in the nature of certiorari quashing the FIR.
"""


def cf_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""BEFORE THE LD. {r.choice(COURTS).upper()}
APPLICATION ON BEHALF OF THE INVESTIGATING OFFICER FOR POLICE CUSTODY REMAND
FIR No. {c['fir_no']}, P.S. {c['ps']}, u/s {c['sec']}
Sir, the accused {c['acc']} was arrested in the above case on {c['d']}. It is submitted that his custodial interrogation is required for recovery of {r.choice(ITEMS)} and to identify the other persons involved. It is therefore prayed that police custody remand of the accused for {r.number(2, 7)} days may kindly be granted.
Applicant: {r.rank_name()}, Investigating Officer                                         Date: {r.date()}
"""


def cf_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""AFFIDAVIT
I, {r.name()}, aged {r.number(25, 65)} years, resident of {c['place']}, do hereby solemnly affirm and declare on oath as under:
1. That I am the deponent in the present case and am well conversant with the facts.
2. That the contents of the accompanying application in Case No. {c['fir_no']} are true and correct to the best of my knowledge.
DEPONENT
VERIFICATION: Verified at {c['dist']} on this {r.date()} that the contents of the above affidavit are true and correct and nothing material has been concealed therefrom.
Attested by the Notary Public / Oath Commissioner
"""


# ------------------------------------------------------------------------------------------ evidence record
def ev_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""SEIZURE MEMO (Under Section 102 Cr.P.C. / Section 106 BNSS)
FIR No. {c['fir_no']}   P.S. {c['ps']}   Date: {c['d']}   Time: {c['t']}
Today at {c['place']} in the presence of the following independent witnesses: 1. {r.title_name()} 2. {r.title_name()}
the undersigned {r.rank_name()} seized the following articles:
1. {r.choice(ITEMS)}
2. {r.choice(ITEMS)}
The articles were placed in a cloth parcel, sealed with the seal of "{c['ps'][:3].upper()}" and signed by the witnesses. A specimen of the seal is affixed below. A copy of this memo was given to {c['acc']} in whose possession the articles were found.
Signature of witnesses          Seizing officer
"""


def ev_1(r: R) -> str:
    c = _case_hdr(r)
    rows = "\n".join(f"{i}. Exhibit {i} | {r.choice(ITEMS)} | collected by {r.rank_name()} | {r.date()} {r.time()} | seal intact" for i in range(1, r.number(3, 6)))
    return f"""CHAIN OF CUSTODY FORM
Case: {c['fir_no']}, P.S. {c['ps']}
No. | Description | Collected by | Date/time | Condition of seal
{rows}
Transferred to: {r.choice(['Malkhana', 'Forensic Science Laboratory', 'Court'])} on {r.date()}   Received by: {r.rank_name()}
Remarks: packages received with the seals intact and matching the specimen seal. Any break in custody must be recorded here.
"""


def ev_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""CASE PROPERTY REGISTER - MALKHANA ENTRY
Malkhana Entry No. {r.number(1, 900)}/{r.year()}    P.S. {c['ps']}    Crime No. {c['fir_no']}
Description of property: {r.choice(ITEMS)}
Date of deposit: {r.date()}    Deposited by: {r.rank_name()}    Seized from: {c['acc']}
Nature of seal: {r.choice(['lac seal', 'cloth parcel with paper seal', 'evidence bag no. ' + str(r.number(1000, 9999))])}
Disposal: {r.choice(['retained pending trial', 'sent to FSL on ' + r.date(), 'released on superdari'])}
Incharge Malkhana signature
"""


def ev_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""LIST OF EXHIBITS - Sessions Case {r.number(1, 300)}/{r.year()}, State vs {c['acc']}
Ex. P-1: sealed packet containing {r.choice(ITEMS)}, seized vide seizure memo dated {r.date()}
Ex. P-2: {r.choice(ITEMS)} recovered at the instance of the accused
Ex. P-3: photographs of the scene of occurrence
Ex. P-4: certificate under Section 65B of the Indian Evidence Act for the electronic record
Material objects are kept in the custody of the court malkhana; the chain of custody of each exhibit is on record.
"""


# ------------------------------------------------------------------------------------------ forensic report
def fo_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""FORENSIC SCIENCE LABORATORY, {c['dist'].upper()}
EXAMINATION REPORT
Laboratory No.: FSL/{r.year()}/{r.number(100, 9999)}     Date of report: {r.date()}
Reference: Letter of the Superintendent of Police, P.S. {c['ps']}, Crime No. {c['fir_no']}
Exhibits received: Ex. 1 - {r.choice(['blood sample of the deceased', 'swab from the scene', 'a knife', 'clothes of the victim'])}; Ex. 2 - {r.choice(['reference blood sample of the accused', 'hair sample', 'a fired cartridge'])}
Examination performed: {r.choice(FSL_TESTS)}
Result: The profile obtained from Ex. 1 {r.choice(['matches', 'does not match'])} the profile of Ex. 2.
Opinion: {r.choice(['The exhibits are of human origin.', 'The individual characteristics are identical.', 'The material is consistent with the reference sample.'])}
Scientific Officer / Assistant Director
"""


def fo_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""FINGER PRINT BUREAU - EXPERT OPINION
Case: {c['fir_no']}, P.S. {c['ps']}
Chance prints developed from the scene of occurrence were marked Q1 to Q{r.number(2, 5)}. The specimen finger impressions of {c['acc']} (S1 to S10) were compared with the chance prints by the ridge characteristics.
Findings: Chance print Q1 has {r.number(9, 16)} ridge characteristics in agreement with the right thumb impression S1 without any unexplained difference.
Opinion: Chance print Q1 is identical with the right thumb impression of the accused. Chance print Q2 is not fit for comparison.
Fingerprint Expert
"""


def fo_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""BALLISTICS EXPERT REPORT
Forensic Science Laboratory, Ballistics Division    Ref. Crime No. {c['fir_no']}    Report No. {r.number(1, 500)}/{r.year()}
Exhibits: one 9 mm country-made pistol (W/1), two fired cartridge cases (EC/1, EC/2), one deformed bullet (B/1)
Test firing was carried out using standard ammunition and the test cartridge cases were compared microscopically with the questioned cartridge cases under a comparison microscope.
Opinion: The questioned cartridge cases EC/1 and EC/2 have been fired from the weapon W/1. The weapon is in working condition.
"""


def fo_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""DIGITAL FORENSICS EXAMINATION REPORT
Case: {c['fir_no']}, P.S. {c['ps']}      Cyber Forensic Laboratory
Device received: {r.choice(['Samsung mobile phone', 'Dell laptop', 'external hard disk'])}, IMEI / serial no. {r.number(100000, 999999)}{r.number(100000, 999999)}
A forensic image of the device was acquired using a hardware write-blocker and its hash value SHA-256 was recorded to prove integrity. The image was analysed for deleted chats, call records and browser history.
Findings: recovered {r.number(12, 480)} WhatsApp messages between the accused and the complainant; the timestamps correspond to {r.date()}.
The examination was carried out in accordance with the standard operating procedure of the laboratory.
"""


# -------------------------------------------------------------------------------------------- legal notice
def ln_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""LEGAL NOTICE
BY REGISTERED POST A.D. / SPEED POST
Date: {c['d']}
To, {c['acc']}, r/o {c['place']}
Under instructions from and on behalf of my client {c['comp']}, I hereby serve upon you the following legal notice:
1. That my client has given you a sum of {r.amount()} on {r.date()} as a friendly loan.
2. That despite repeated requests you have failed to repay the amount.
You are hereby called upon to pay the said amount within 15 days of receipt of this notice, failing which my client shall be constrained to initiate appropriate civil and criminal proceedings against you at your risk as to costs and consequences.
{r.title_name()}, Advocate, {c['dist']}
"""


def ln_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""NOTICE UNDER SECTION 138 OF THE NEGOTIABLE INSTRUMENTS ACT, 1881
To, M/s {r.name(False)} Traders, {c['place']}
Under instructions of my client I state that you issued cheque No. {r.number(100000, 999999)} dated {r.date()} for {r.amount()} drawn on {r.choice(BANKS)}, which was returned unpaid with the remark "funds insufficient" as per the return memo dated {r.date()}.
You are hereby called upon to make the payment within fifteen days of receipt of this notice, failing which my client will file a complaint before the competent court under Section 138 of the Act.
Advocate for the payee
"""


def ln_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""NOTICE UNDER SECTION 35 BNSS / 41A Cr.P.C.
Police Station {c['ps']}, {c['dist']}    Case Crime No. {c['fir_no']}    Date: {c['d']}
To, {c['acc']}, r/o {c['place']}
Whereas a complaint has been received against you in connection with {c['off']['en']}, you are hereby directed to appear before the undersigned on {r.date()} at {r.time()} at the police station to answer questions relating to the case. If you fail to comply with the terms of this notice you are liable to be arrested.
{r.rank_name()}, Investigating Officer
"""


def ln_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""NOTICE UNDER SECTION 80 OF THE CODE OF CIVIL PROCEDURE
To, The Secretary, Department of {r.choice(['Revenue', 'Home', 'Public Works', 'Transport'])}, State Government
My client {c['comp']} hereby gives you notice of his intention to institute a suit for damages of {r.amount()} against the State for wrongful acts of its officers on {r.date()}. The cause of action arose at {c['place']}. If the claim is not satisfied within two months from the date of delivery of this notice, my client will be compelled to file a civil suit.
Counsel for the claimant
"""


# ------------------------------------------------------------------------------------------------ judgment
def jg_0(r: R) -> str:
    c = _case_hdr(r)
    verdict = r.choice(["convicted", "acquitted"])
    tail = (f"The accused is hereby convicted under {c['sec']} and sentenced to rigorous imprisonment for {r.number(1, 10)} years and a fine of {r.amount()}."
            if verdict == "convicted" else
            "The prosecution has failed to prove the guilt of the accused beyond reasonable doubt. The accused is acquitted and his bail bonds are discharged.")
    return f"""IN THE COURT OF THE {r.choice(COURTS).upper()}, {c['dist'].upper()}
Sessions Case No. {r.number(1, 400)}/{r.year()}          State vs {c['acc']}
JUDGMENT
The accused stands charged for the offence punishable under {c['sec']}. The prosecution examined PW-1 to PW-{r.number(4, 10)}. The statement of the accused under Section 313 Cr.P.C. was recorded. I have heard the learned Public Prosecutor and the counsel for the accused and perused the record.
Point for determination: whether the prosecution has proved that the accused {c['off']['act']}.
Finding: {tail}
Pronounced in open court on {r.date()}.
"""


def jg_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""ORDER SHEET
IN THE COURT OF THE {r.choice(COURTS).upper()}
Case: State vs {c['acc']}, FIR {c['fir_no']}          Date: {r.date()}
Present: Ld. APP for the State; Ld. counsel for the accused.
Heard on the bail application. The offence alleged is {c['off']['en']}. Considering the period of custody and that the charge sheet has been filed, the accused is admitted to bail on furnishing a personal bond of {r.amount()} with one surety of the like amount, subject to the condition that he shall not tamper with the evidence.
Application disposed of. Next date of hearing: {r.date()}.
"""


def jg_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""IN THE HIGH COURT OF {r.choice(HIGH_COURTS).upper()}
CRIMINAL APPEAL No. {r.number(1, 3000)} of {r.year()}
{c['acc']} ... Appellant   Versus   State ... Respondent
Reserved on: {r.date()}      Pronounced on: {r.date()}
JUDGMENT
This appeal is directed against the judgment of the trial court convicting the appellant under {c['sec']}. Having considered the evidence of the eyewitnesses and the medical evidence, this Court finds no infirmity in the findings recorded. The appeal is accordingly {r.choice(['dismissed', 'partly allowed and the sentence is reduced to the period already undergone'])}.
"""


def jg_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""ORDER ON CHARGE
{r.choice(COURTS)}, {c['dist']}     Case No. {r.number(1, 300)}/{r.year()}     State vs {c['acc']}
After hearing both sides and perusing the charge sheet and documents filed under Section 173 Cr.P.C., the court is of the opinion that there is sufficient ground to presume that the accused has committed the offence under {c['sec']}. Charge is therefore framed against the accused, read over and explained to him in the language he understands. He pleaded not guilty and claimed trial. The case is posted for prosecution evidence on {r.date()}.
"""


# ------------------------------------------------------------------------------------------ medical report
def md_0(r: R) -> str:
    c = _case_hdr(r)
    inj = r.pick_n(INJURIES, 2, 3)
    return f"""MEDICO-LEGAL CERTIFICATE (MLC)
Government {r.choice(['District Hospital', 'Civil Hospital', 'Medical College Hospital'])}, {c['dist']}       MLC No. {r.number(1, 9999)}/{r.year()}
Name: {r.name()}    Age: {r.number(5, 70)} years    Sex: {r.choice(['Male', 'Female'])}
Brought by: Constable {r.name(False)} of P.S. {c['ps']} on {c['d']} at {c['t']}
History as narrated by the patient: assault by known persons with a blunt object.
On examination the following injuries were noted: 1. {inj[0]} 2. {inj[1]}
Opinion: The injuries are simple in nature, caused by a blunt object, and about {r.number(6, 48)} hours old. No danger to life.
Medical Officer, signature and seal
"""


def md_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""POST-MORTEM EXAMINATION REPORT
Post-mortem No. {r.number(1, 900)}/{r.year()}    Hospital: {c['dist']}    Inquest reference: FIR {c['fir_no']}, P.S. {c['ps']}
Name of the deceased: {r.name()}, aged about {r.number(15, 80)} years, {r.choice(['male', 'female'])}
The body was received in a sealed condition with the police papers and was identified by the relatives. Rigor mortis and post-mortem staining were noted. External and internal examination revealed the findings recorded in the annexure.
Cause of death: {r.choice(['injury to vital organs', 'asphyxia', 'shock and haemorrhage'])}. Time since death: about {r.number(6, 48)} hours. Viscera has been preserved and sealed for chemical analysis.
Autopsy Surgeon
"""


def md_2(r: R) -> str:
    c = _case_hdr(r)
    inj = r.pick_n(INJURIES, 1, 2)
    return f"""INJURY REPORT AND DISCHARGE SUMMARY
Patient: {r.name()} ({r.number(5, 70)} years)    Hospital: {r.choice(['City Hospital', 'Trauma Centre', 'Community Health Centre'])}, {c['dist']}
Date of admission: {r.date()}    Date of discharge: {r.date()}
Presenting complaint: pain after a fall / assault. Findings: {inj[0]}. X-ray: no fracture seen. Treatment given: dressing, analgesics, tetanus toxoid. Advised follow-up after 5 days. Medico-legal case intimated to the police station.
Treating Doctor
"""


def md_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""MEDICAL EXAMINATION OF THE ACCUSED
Requisition of the Investigating Officer, P.S. {c['ps']}, Crime No. {c['fir_no']}
Name: {c['acc']}    Age: {r.number(20, 55)} years    Examined on: {c['d']}
The accused was medically examined in the presence of a police escort with his consent. General condition is good. Pulse and blood pressure are normal. Marks of identification: a scar on the left forearm. No fresh external injury was noticed. He is medically fit for interrogation and for being produced before the court.
Medical Officer
"""


# ---------------------------------------------------------------------------------------- arrest warrant
def aw_0(r: R) -> str:
    c = _case_hdr(r)
    return f"""WARRANT OF ARREST
(Section 70 Cr.P.C.)
IN THE COURT OF THE {r.choice(COURTS).upper()}, {c['dist'].upper()}
To, The Superintendent of Police, {c['dist']}
Whereas {c['acc']}, son of {r.name(False)}, resident of {c['place']}, stands accused of the offence of {c['off']['en']} punishable under {c['sec']}, and it has been made to appear that he has absconded and is not available for service of summons,
You are hereby directed to arrest the said {c['acc'].split()[-1]} and to produce him before this Court on or before {r.date()}.
Given under my hand and the seal of the Court this {r.date()}.
Judicial Magistrate
"""


def aw_1(r: R) -> str:
    c = _case_hdr(r)
    return f"""NON-BAILABLE WARRANT
Court of the {r.choice(COURTS)}, {c['dist']}       Case No. {r.number(1, 900)}/{r.year()}       Crime No. {c['fir_no']}, P.S. {c['ps']}
To: The Station House Officer, P.S. {c['ps']}
The accused {c['acc']} has failed to appear despite service of summons and bailable warrants. The Station House Officer is directed to execute this non-bailable warrant, arrest the accused wherever found and produce him before this Court on {r.date()}. Return the warrant with an endorsement showing the manner of execution.
Issued on {r.date()} under the signature and seal of the Court.
"""


def aw_2(r: R) -> str:
    c = _case_hdr(r)
    return f"""PROCLAMATION AND WARRANT UNDER SECTION 82 Cr.P.C. / 84 BNSS
{r.choice(COURTS)}, {c['dist']}
Whereas a warrant of arrest issued against {c['acc']}, resident of {c['place']}, accused in Crime No. {c['fir_no']} u/s {c['sec']}, could not be executed as he is absconding, this proclamation requires the said person to appear before this Court on or before {r.date()}. Failing which he shall be declared a proclaimed offender and his property shall be liable to attachment.
Issued by the Court on {r.date()}.
"""


def aw_3(r: R) -> str:  # held out
    c = _case_hdr(r)
    return f"""BAILABLE WARRANT (Section 76 Cr.P.C.)
To the Officer in charge of {c['ps']} Police Station
You are hereby commanded to arrest {c['acc']} of {c['place']}, accused of {c['off']['en']}, and to bring him before this Court unless he furnishes security in a sum of {r.amount()} for his appearance on {r.date()}.
Given under my hand and seal. Magistrate, {c['dist']}
"""


# ---------------------------------------------------------------------------------------------- other
def ot_0(r: R) -> str:
    return f"""OFFICE MEMORANDUM
No. {r.number(1, 900)}/Admin/{r.year()}          Date: {r.date()}
Subject: Annual departmental training and leave roster
All staff are informed that the annual training programme will be held from {r.date()} to {r.date()} at the district headquarters. Casual leave will not be granted during this period except in emergencies. The canteen will remain closed on {r.date()} for maintenance. Officers are requested to submit their preferred training modules to the establishment section by the end of the week.
Superintendent (Administration)
"""


def ot_1(r: R) -> str:
    return f"""TAX INVOICE
{r.name(False)} Enterprises, {r.place()}      GSTIN: {r.number(10, 36)}ABCDE{r.number(1000, 9999)}F1Z5
Invoice No.: INV-{r.number(1000, 99999)}     Date: {r.date()}
Item                         Qty    Rate      Amount
Printer cartridge             {r.number(1, 9)}      {r.number(500, 4000)}     {r.number(1000, 20000)}
A4 paper reams               {r.number(5, 40)}      {r.number(200, 400)}     {r.number(2000, 12000)}
Total payable: {r.amount()}   Payment mode: {r.choice(['UPI', 'cheque', 'bank transfer'])}
Thank you for your business.
"""


def ot_2(r: R) -> str:
    return f"""Dear {r.name()},
I hope you are doing well. I am writing to share the details of the family function on {r.date()}. We have booked the community hall near {r.choice(['the temple', 'the park', 'the market'])} and lunch will be served at {r.time()}. Please let me know how many guests will be coming so that we can arrange the seating. It would be lovely if you could bring the photographs from last year.
With love,
{r.name()}
"""


def ot_3(r: R) -> str:
    return f"""MINUTES OF THE MEETING OF THE RESIDENTS' WELFARE ASSOCIATION
Date: {r.date()}   Venue: {r.place()}   Members present: {r.number(8, 40)}
Agenda: 1. Approval of last month's minutes 2. Water supply and street lighting 3. Annual maintenance charges 4. Any other matter
Decisions: the maintenance charge will be revised to {r.amount()} per month; a complaint will be sent to the municipal corporation about the delayed garbage collection; the next meeting will be held on {r.date()}.
Vote of thanks by the Secretary.
"""


def ot_4(r: R) -> str:
    return f"""RIGHT TO INFORMATION - REPLY
Reference: RTI Application No. {r.number(1, 999)}/{r.year()} dated {r.date()}
Public Information Officer, Office of the District Collector, {r.district()}
With reference to your application, the information sought regarding the number of road repair works sanctioned in the last financial year is enclosed as Annexure A. Information relating to the tender file is denied under Section 8(1)(d) of the RTI Act. If you are not satisfied you may prefer a first appeal within 30 days.
"""


def ot_5(r: R) -> str:
    return f"""PRESS NOTE
{r.district()}, {r.date()}
The district administration will organise a road safety awareness rally on {r.date()} starting from {r.choice(['the town hall', 'the railway station', 'the stadium'])}. School students, volunteers and traffic personnel will take part. Citizens are requested to follow traffic rules and wear helmets. Free health check-up camps will also be held at {r.place()}.
Issued by the Public Relations Officer
"""


EN: dict[str, list] = {
    "fir": [fir_0, fir_1, fir_2, fir_3],
    "police_report": [pr_0, pr_1, pr_2, pr_3],
    "investigation_record": [inv_0, inv_1, inv_2, inv_3],
    "witness_statement": [ws_0, ws_1, ws_2, ws_3],
    "charge_sheet": [cs_0, cs_1, cs_2, cs_3],
    "court_filing": [cf_0, cf_1, cf_2, cf_3],
    "evidence_record": [ev_0, ev_1, ev_2, ev_3],
    "forensic_report": [fo_0, fo_1, fo_2, fo_3],
    "legal_notice": [ln_0, ln_1, ln_2, ln_3],
    "judgment": [jg_0, jg_1, jg_2, jg_3],
    "medical_report": [md_0, md_1, md_2, md_3],
    "arrest_warrant": [aw_0, aw_1, aw_2, aw_3],
    "other": [ot_0, ot_1, ot_2, ot_3, ot_4, ot_5],
}


def ot_6(r: R) -> str:
    return f"""RENT AGREEMENT
This agreement is made on {r.date()} between {r.title_name()} (hereinafter the "Landlord") and {r.title_name()} (hereinafter the "Tenant") in respect of the flat at {r.place()}.
WHEREAS the Landlord is the owner of the premises and has agreed to let it on a monthly rent of {r.amount()}, and WHEREAS the Tenant has paid a security deposit of {r.amount()}:
1. The tenancy shall commence on {r.date()} for a period of eleven months. 2. The Tenant shall not sublet the premises. 3. Either party may terminate the tenancy by giving one month's notice.
IN WITNESS WHEREOF the parties have signed below in the presence of two witnesses.
"""


def ot_7(r: R) -> str:
    rows = "\n".join(f"{r.date()}   {r.choice(['UPI transfer', 'ATM withdrawal', 'Salary credit', 'Electricity bill', 'Cheque deposit'])}   {r.number(100, 90000)}   {r.number(1000, 400000)}" for _ in range(r.number(4, 7)))
    return f"""{r.choice(BANKS)} - STATEMENT OF ACCOUNT
Account holder: {r.name()}    Account No. XXXX{r.number(1000, 9999)}    Branch: {r.district()}
Statement period: {r.date()} to {r.date()}
Date        Particulars        Amount        Balance
{rows}
This is a computer generated statement and does not require a signature.
"""


EN["other"].extend([ot_6, ot_7])
