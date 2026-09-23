from __future__ import annotations

from app.grounding import ground, unsupported

SOURCE = ("Forensic laboratory report. DNA profiling of the blood sample recovered from the scooter matched the reference "
          "sample of the suspect Suresh Verma. Report dated 02/04/2026. The vehicle UP 32 AB 1234 was valued at Rs. 45,000. "
          "Contact 9876543210. Registered under Section 379 IPC.")


def test_the_observed_hallucination_is_removed():
    """The 3B model wrote this for the document above: the section number appears nowhere in the source."""
    summary = ("The forensic laboratory report dated 02/04/2026 concluded that a DNA profile matched the suspect Suresh Verma. "
               "This evidence aligns with Section 324 of the Indian Penal Code, which deals with assault and criminal force to woman. "
               "The report supports the connection between the scooter and the suspect.")
    clean, removed = ground(summary, SOURCE)
    assert "324" not in clean and "assault" not in clean
    assert removed == ["section 324 IPC"]
    assert "02/04/2026" in clean and "Suresh Verma" in clean and clean.count(".") >= 2      # the supported sentences survive


def test_supported_facts_pass_even_when_reformatted():
    for text in ("The report is dated 2 April 2026.", "It was valued at Rs. 45000.", "Section 379 of the Indian Penal Code applies.",
                 "Call 98765 43210.".replace(" ", ""), "Vehicle UP32AB1234 was involved."):
        assert unsupported(text, SOURCE) == [], text


def test_invented_identifiers_are_caught():
    assert unsupported("It was dated 15 May 2026.", SOURCE) == ["date 15 May 2026"]
    assert unsupported("The loss was Rs. 90,000.", SOURCE) == ["amount Rs. 90,000"]
    assert unsupported("Call 9123456780.", SOURCE) == ["phone 9123456780"]
    assert unsupported("Vehicle MH 12 AB 9999.", SOURCE) == ["vehicle MH 12 AB 9999"]
    assert unsupported("Under Section 302 BNS.", SOURCE) == ["section 302 BNS"]


def test_facts_free_text_and_edge_cases():
    text = "The suspect was identified from the sample."
    assert ground(text, SOURCE) == (text, [])
    assert ground("", SOURCE) == ("", [])
    clean, removed = ground("Section 999 applies. Section 888 applies.", SOURCE)
    assert clean == "" and len(removed) == 2                                  # nothing supportable -> nothing kept
    assert unsupported("धारा ३७९ के अंतर्गत मामला।", SOURCE) == []            # Devanagari digits are normalised
    assert unsupported("धारा ५०६ के अंतर्गत मामला।", SOURCE) == ["section 506"]


def test_leading_zeros_do_not_matter_but_partial_numbers_do():
    assert unsupported("Section 37 applies.", SOURCE) == ["section 37"]         # 37 is not 379
    assert unsupported("Dated 2/4/2026.", SOURCE) == []
