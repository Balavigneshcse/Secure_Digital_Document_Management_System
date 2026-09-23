from __future__ import annotations

from app import entities

FIR = """District: Lucknow   P.S.: Kotwali   FIR No.: 142/2026   Date: 12/03/2026
Acts & Sections: 379 IPC, 34 IPC and Section 302 of the Indian Penal Code
Complainant: Mr. Ramesh Kumar, resident of Gandhi Nagar, mobile 9876543210. Accused: Mr. Suresh Verma
scooter UP 32 AB 1234 valued at Rs. 45,000 (Rs.1,200 extra). S. 420 IPC. u/s 406, 34"""


def test_amounts_are_not_mistaken_for_sections():
    """'Rs. 45,000' contains 's.' + digits; it once produced bogus sections '45' and '000'."""
    e = entities.extract(FIR)
    assert e["amounts"] == ["Rs. 45,000", "Rs. 1,200"]
    assert set(e["sections"]) >= {"379 IPC", "34 IPC", "302 IPC", "420 IPC"}
    assert not {"45", "000", "1", "200"} & set(e["sections"])


def test_english_fields():
    e = entities.extract(FIR)
    assert e["persons"] == ["Ramesh Kumar", "Suresh Verma"]
    assert {"Lucknow", "Kotwali", "Gandhi Nagar"} <= set(e["locations"])   # "District: Lucknow" (with a colon) included
    assert e["dates"] == ["12/03/2026"] and e["case_numbers"] == ["142/2026"]
    assert e["phones"] == ["9876543210"] and e["vehicles"] == ["UP 32 AB 1234"]


def test_hindi_names_and_places_without_postpositions():
    e = entities.extract("साधारण डायरी: थाना कोतवाली में श्री रमेश कुमार ने पड़ोसी के साथ शिकायत दी। धारा 323 भा.दं.सं. जिला लखनऊ")
    assert e["persons"] == ["रमेश कुमार"]
    assert "कोतवाली" in e["locations"] and "लखनऊ" in e["locations"] and "कोतवाली में" not in e["locations"]
    assert e["sections"] == ["323 IPC"]


def test_tamil_and_indic_numerals():
    e = entities.extract("பிரிவு ३७९ இ.த.ச கீழ் வழக்கு. காவல் நிலையம் கோட்டை, மாவட்டம் சென்னை. நான் ரமேஷ் குமார், வயது 40")
    assert e["sections"] == ["379 IPC"]              # Devanagari digits are normalised
    assert e["persons"] == ["ரமேஷ் குமார்"] and {"கோட்டை", "சென்னை"} <= set(e["locations"])


def test_new_criminal_laws_and_offence_tags():
    e = entities.extract("Registered under Section 303(2) BNS and Sections 103(1), 3(5) BNS; Section 66C of the IT Act.")
    assert {"303(2) BNS", "103(1) BNS"} <= set(e["sections"])
    tags = entities.offence_tags(["302 IPC", "303(2) BNS", "498A IPC", "999 IPC"])
    assert tags == ["murder", "theft", "cruelty to wife"]


def test_empty_and_noise_do_not_crash():
    assert all(v == [] for v in entities.extract("").values())
    assert entities.extract("!!! ### 000 --- ,,,")["sections"] == []
