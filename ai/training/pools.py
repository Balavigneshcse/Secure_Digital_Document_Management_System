"""Shared value pools and a seeded random helper used by the synthetic-corpus generators.

Everything here is fictional: names, numbers and places are randomly combined and do not identify anyone.
"""
from __future__ import annotations

import datetime as dt
import random

LABELS = [
    "fir", "police_report", "investigation_record", "witness_statement", "charge_sheet", "court_filing",
    "evidence_record", "forensic_report", "legal_notice", "judgment", "medical_report", "arrest_warrant", "other",
]

MALE = ["Ramesh", "Suresh", "Mahesh", "Rajesh", "Vikram", "Amit", "Sanjay", "Anil", "Manoj", "Deepak", "Rahul", "Arun",
        "Prakash", "Naveen", "Karthik", "Mohammed", "Imran", "Faisal", "Gurpreet", "Harpreet", "Sunil", "Vijay", "Ashok",
        "Ravi", "Kiran", "Sandeep", "Pradeep", "Nitin", "Rohit", "Yogesh", "Bharat", "Murugan", "Selvam", "Senthil", "Arjun"]
FEMALE = ["Anita", "Sunita", "Priya", "Kavita", "Meena", "Rekha", "Pooja", "Neha", "Sushma", "Lakshmi", "Geeta", "Shanti",
          "Radha", "Asha", "Divya", "Fatima", "Ayesha", "Kavya", "Sneha", "Revathi", "Latha", "Savita", "Nisha"]
SURNAME = ["Kumar", "Sharma", "Verma", "Singh", "Yadav", "Gupta", "Patel", "Reddy", "Nair", "Iyer", "Das", "Khan", "Ansari",
           "Mishra", "Joshi", "Chauhan", "Rao", "Pillai", "Naidu", "Thakur", "Mehta", "Banerjee", "Sen", "Kapoor", "Malhotra",
           "Bhat", "Menon", "Shetty", "Gowda", "Pandey", "Tiwari", "Saxena", "Agarwal", "Jain", "Chaudhary", "Rathore", "Bose"]
STATIONS = ["Kotwali", "Civil Lines", "Sadar Bazar", "Model Town", "Gandhi Nagar", "Cantonment", "Rajiv Chowk", "Station Road",
            "Old City", "New Colony", "Lal Darwaza", "Ashok Vihar", "Sector 14", "Cyber Crime Cell", "Women Police Station",
            "Transport Nagar", "Industrial Area", "Bus Stand", "Railway Colony", "Mahila Thana"]
DISTRICTS = ["Lucknow", "Jaipur", "Pune", "Nagpur", "Bhopal", "Indore", "Chennai", "Madurai", "Coimbatore", "Hyderabad", "Patna",
             "Ranchi", "Guwahati", "Chandigarh", "Ludhiana", "Amritsar", "Kanpur", "Varanasi", "Agra", "Surat", "Vadodara",
             "Kochi", "Mysuru", "Bengaluru", "Kolkata", "Bhubaneswar", "Dehradun", "Raipur", "Meerut", "Nashik", "Delhi"]
LOCALITIES = ["Sector 9", "Gandhi Chowk", "Nehru Market", "Shastri Nagar", "Ambedkar Colony", "Green Park", "Tilak Road",
              "MG Road", "Rampur Village", "Bhagat Singh Chowk", "Vasant Vihar", "Krishna Nagar", "Subhash Marg", "Laxmi Nagar",
              "Patel Nagar", "Anna Salai", "Temple Street", "Market Yard", "Housing Board Colony", "Lake View Road"]
COURTS = ["Chief Judicial Magistrate", "Additional Sessions Judge", "Metropolitan Magistrate", "Sessions Judge",
          "Judicial Magistrate First Class", "Special Judge (POCSO)", "Additional Chief Metropolitan Magistrate"]
HIGH_COURTS = ["Allahabad", "Bombay", "Madras", "Delhi", "Karnataka", "Punjab and Haryana", "Rajasthan", "Kerala", "Patna", "Calcutta"]
RANKS = ["Inspector", "Sub-Inspector", "Assistant Sub-Inspector", "Head Constable", "Deputy Superintendent of Police"]
OCCUPATIONS = ["shopkeeper", "teacher", "driver", "labourer", "student", "farmer", "clerk", "engineer", "nurse", "businessman",
               "tailor", "electrician", "auto-rickshaw driver", "bank employee", "housewife", "security guard"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

# name_en, act phrase, IPC sections, BNS sections
OFFENCES = [
    dict(en="theft of a motorcycle", act="committed theft of a motorcycle", ipc=["379"], bns=["303(2)"]),
    dict(en="house-breaking and theft", act="broke into the house and committed theft", ipc=["457", "380"], bns=["331(4)", "305"]),
    dict(en="robbery at knife-point", act="committed robbery at knife-point", ipc=["392", "34"], bns=["309(4)", "3(5)"]),
    dict(en="voluntarily causing hurt", act="assaulted him with a wooden rod causing hurt", ipc=["323", "324"], bns=["115(2)", "118(1)"]),
    dict(en="attempt to murder", act="attacked with a sharp weapon with intent to kill", ipc=["307"], bns=["109(1)"]),
    dict(en="murder", act="caused the death of the deceased", ipc=["302", "34"], bns=["103(1)", "3(5)"]),
    dict(en="cheating and fraud", act="cheated by dishonestly inducing delivery of money", ipc=["420", "406"], bns=["318(4)", "316(2)"]),
    dict(en="forgery", act="forged documents and used them as genuine", ipc=["467", "468", "471"], bns=["338", "336(3)", "340(2)"]),
    dict(en="criminal intimidation", act="threatened to cause harm and extorted money", ipc=["506", "384"], bns=["351(2)", "308(2)"]),
    dict(en="cruelty by husband and relatives", act="subjected the complainant to cruelty for dowry", ipc=["498A", "406"], bns=["85", "316(2)"]),
    dict(en="stalking", act="repeatedly followed and contacted the complainant despite refusal", ipc=["354D"], bns=["78"]),
    dict(en="kidnapping", act="kidnapped the minor from lawful guardianship", ipc=["363", "366"], bns=["137(2)", "140(3)"]),
    dict(en="identity theft over the internet", act="cheated by personation using a computer resource", ipc=["419", "420"], bns=["319(2)", "318(4)"]),
    dict(en="possession of narcotics", act="was found in possession of a commercial quantity of a narcotic substance", ipc=[], bns=[]),
    dict(en="rash driving causing death", act="caused death by rash and negligent driving", ipc=["304A", "279"], bns=["106(1)", "281"]),
]
ITEMS = ["a black Honda Activa scooter", "one Samsung Galaxy mobile phone", "a gold chain weighing about 20 grams",
         "cash amounting to Rs. 45,000", "a laptop (Dell Inspiron)", "one country-made pistol", "a blood-stained shirt",
         "a sealed packet containing white powder", "one iron rod", "a bunch of keys", "a debit card and wallet",
         "a silver anklet pair", "one CCTV DVR unit", "a motorcycle bearing registration DL 8S AB 1234"]
INJURIES = ["an abrasion 3 cm x 2 cm on the left forearm", "a lacerated wound 4 cm long over the scalp", "contusion 5 cm x 3 cm on the right thigh",
            "a bruise over the right shoulder", "swelling and tenderness over the left wrist", "an incised wound 2 cm on the palm"]
FSL_TESTS = ["DNA profiling by STR analysis", "comparison of chance fingerprints", "ballistic examination of the fired cartridge",
             "chemical analysis of the viscera", "examination of the questioned handwriting", "analysis of the seized mobile phone",
             "comparison of tool marks", "toxicological analysis of the blood sample"]
BANKS = ["State Bank of India", "Punjab National Bank", "HDFC Bank", "ICICI Bank", "Canara Bank", "Bank of Baroda"]


class R(random.Random):
    """Seeded random with helpers for fictional Indian case details."""

    def name(self, female: bool | None = None) -> str:
        female = self.random() < 0.4 if female is None else female
        return f"{self.choice(FEMALE if female else MALE)} {self.choice(SURNAME)}"

    def title_name(self, female: bool | None = None) -> str:
        n = self.name(female)
        return f"{self.choice(['Smt.', 'Mrs.', 'Ms.']) if female else self.choice(['Mr.', 'Shri', 'Sh.'])} {n}"

    def rank_name(self) -> str:
        return f"{self.choice(RANKS)} {self.name(False)}"

    def station(self) -> str:
        return self.choice(STATIONS)

    def district(self) -> str:
        return self.choice(DISTRICTS)

    def place(self) -> str:
        return f"{self.choice(LOCALITIES)}, {self.district()}"

    def date_obj(self, year_min=2019, year_max=2026) -> dt.date:
        start = dt.date(year_min, 1, 1)
        return start + dt.timedelta(days=self.randint(0, (dt.date(year_max, 9, 1) - start).days))

    def date(self, d: dt.date | None = None, style: int | None = None) -> str:
        d = d or self.date_obj()
        style = self.randint(0, 3) if style is None else style
        return [f"{d.day:02d}/{d.month:02d}/{d.year}", f"{d.day:02d}-{d.month:02d}-{d.year}",
                f"{d.day} {MONTHS[d.month - 1]} {d.year}", f"{d.year}-{d.month:02d}-{d.day:02d}"][style]

    def time(self) -> str:
        return f"{self.randint(0, 23):02d}:{self.choice(['00', '15', '30', '45', '10', '20', '50'])} hrs"

    def phone(self) -> str:
        return f"{self.choice(['98', '99', '97', '90', '88', '70', '63'])}{self.randint(10000000, 99999999)}"

    def vehicle(self) -> str:
        return f"{self.choice(['DL', 'UP', 'MH', 'TN', 'KA', 'RJ', 'GJ', 'MP', 'HR', 'PB'])} {self.randint(1, 20):02d}{self.choice(['A', 'C', 'S', 'B'])} {self.choice(['AB', 'CD', 'XY', 'MK', 'PL'])} {self.randint(1000, 9999)}"

    def amount(self) -> str:
        v = self.choice([5000, 12000, 25000, 45000, 75000, 150000, 320000, 1200000])
        return f"Rs. {v:,}" if self.random() < 0.7 else f"INR {v}"

    def offence(self) -> dict:
        return self.choice(OFFENCES)

    def sections(self, off: dict, new_law: bool | None = None) -> str:
        new_law = self.random() < 0.35 if new_law is None else new_law
        if not off["ipc"]:
            return "Section 21, 22 and 29 of the NDPS Act, 1985" if self.random() < 0.7 else "Section 20 of the NDPS Act"
        if new_law:
            return ", ".join(f"Section {s} BNS" for s in off["bns"])
        style = self.choice(["ipc", "ipcdot", "sect"])
        if style == "ipc":
            return ", ".join(f"{s} IPC" for s in off["ipc"])
        if style == "ipcdot":
            return "u/s " + ", ".join(off["ipc"]) + " I.P.C."
        return " and ".join(f"Section {s} of the Indian Penal Code" for s in off["ipc"])

    def number(self, lo=1, hi=999) -> int:
        return self.randint(lo, hi)

    def year(self) -> int:
        return self.randint(2019, 2026)

    def pick_n(self, seq, lo, hi):
        return self.sample(list(seq), min(len(seq), self.randint(lo, hi)))
