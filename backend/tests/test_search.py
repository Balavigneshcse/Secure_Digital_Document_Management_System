from __future__ import annotations

from datetime import date, timedelta

from conftest import FIR_TEXT

WITNESS = b"""STATEMENT OF WITNESS under Section 161 CrPC
I, Mrs. Anita Sharma, r/o Village Rampur, state that on 13/03/2026 I saw Mr. Suresh Verma near the shop.
"""


def _setup(world):
    c1 = world.make_case("officer1", title="Market theft", fir_number="FIR-142/2026")
    d1 = world.upload(c1["id"], data=FIR_TEXT, name="fir.txt", title="FIR theft")
    d2 = world.upload(c1["id"], data=WITNESS, name="w.txt", title="Witness statement Anita")
    c2 = world.make_case("officer2", title="Cyber fraud", fir_number="FIR-7/2026", parties=[{"name": "Priya Nair", "role": "victim"}])
    d3 = world.upload(c2["id"], "officer2", data=b"Complaint about online fraud by Mr. Rahul Das", name="c.txt", title="Complaint")
    return c1, c2, d1, d2, d3


def _docs(r):
    return sorted(d["document_id"] for d in r.json()["documents"])


def test_full_text_search_over_ocr_content(world):
    c1, c2, d1, d2, d3 = _setup(world)
    r = world.client.get("/api/search", headers=world.h("officer1"), params={"q": "Rampur"})
    assert _docs(r) == [d2["id"]]
    assert "Rampur" in r.json()["documents"][0]["snippet"]


def test_search_by_entity_party_case_and_fir(world):
    c1, c2, d1, d2, d3 = _setup(world)
    h = world.h("officer1")
    q = lambda **p: world.client.get("/api/search", headers=h, params=p)  # noqa: E731
    assert _docs(q(party="Suresh Verma")) == sorted([d1["id"], d2["id"]])  # named inside the documents
    assert _docs(q(party="Ramesh Kumar")) == sorted([d1["id"], d2["id"]])  # registered party of the case
    assert _docs(q(case_number=c1["case_number"])) == sorted([d1["id"], d2["id"]])
    assert _docs(q(fir_number="142/2026")) == sorted([d1["id"], d2["id"]])
    assert _docs(q(q="379")) == [d1["id"]]  # section of law extracted by the AI layer
    assert _docs(q(doc_type="witness_statement")) == [d2["id"]]
    assert [c["case_number"] for c in q(party="Ramesh").json()["cases"]] == [c1["case_number"]]


def test_search_by_date_range(world):
    c1, *_ = _setup(world)
    h = world.h("officer1")
    today = date.today()
    hit = world.client.get("/api/search", headers=h, params={"date_from": str(today - timedelta(days=1)), "date_to": str(today + timedelta(days=1))})
    assert len(hit.json()["documents"]) == 2
    miss = world.client.get("/api/search", headers=h, params={"date_to": str(today - timedelta(days=2))})
    assert miss.json()["documents"] == []
    assert world.client.get("/api/search", headers=h, params={"date_from": "yesterday"}).status_code == 422


def test_search_never_leaks_other_officers_cases(world):
    c1, c2, d1, d2, d3 = _setup(world)
    r = world.client.get("/api/search", headers=world.h("officer2"), params={"q": "fraud"})
    assert _docs(r) == [d3["id"]]
    assert all(c["case_number"] == c2["case_number"] for c in r.json()["cases"])
    # Content of case 1 is invisible to officer2 by any route.
    for term in ("Rampur", "Ramesh", "Suresh", c1["case_number"], "FIR-142"):
        r = world.client.get("/api/search", headers=world.h("officer2"), params={"q": term})
        assert r.json()["documents"] == [] and r.json()["cases"] == [], term


def test_admin_search_is_case_metadata_only(world):
    c1, c2, d1, d2, d3 = _setup(world)
    r = world.client.get("/api/search", headers=world.h("admin1"), params={"q": "Rampur"})
    assert r.json()["documents"] == [] and r.json()["cases"] == []  # OCR content not searchable by admin
    r = world.client.get("/api/search", headers=world.h("admin1"), params={"party": "Priya"})
    assert [c["case_number"] for c in r.json()["cases"]] == [c2["case_number"]]
    assert r.json()["documents_total"] is None


def test_case_search_matches_the_description_field(world):
    """Regression: `q` only matched title/case_number/fir_number/parties, silently missing the description."""
    c = world.make_case("officer1", title="Assault outside a marriage hall",
                        description="Altercation between two families during a wedding function; one injured party.")
    r = world.client.get("/api/search", headers=world.h("officer1"), params={"q": "wedding"})
    assert [x["case_number"] for x in r.json()["cases"]] == [c["case_number"]]
    r = world.client.get("/api/search", headers=world.h("admin1"), params={"q": "wedding"})  # metadata-only role too
    assert [x["case_number"] for x in r.json()["cases"]] == [c["case_number"]]


def test_like_wildcards_are_escaped(world):
    _setup(world)
    h = world.h("officer1")
    for term in ("%", "_", "\\"):  # SQL LIKE wildcards must match nothing, not everything
        r = world.client.get("/api/search", headers=h, params={"q": term})
        assert r.json()["documents"] == [], term
    r = world.client.get("/api/search", headers=h, params={"q": "FIR t%ft"})  # wildcard inside a real title
    assert r.json()["documents"] == []


def test_content_search_is_whole_word_and_case_insensitive(world):
    """Document text is only stored encrypted, searchable through a keyed word index: whole words, not substrings."""
    c1, c2, d1, d2, d3 = _setup(world)
    h = world.h("officer1")
    q = lambda t: _docs(world.client.get("/api/search", headers=h, params={"q": t}))  # noqa: E731
    assert q("RAMPUR") == q("rampur") == [d2["id"]]
    assert q("Ramp") == []                                   # prefix of a word: not matched (documented limitation)
    assert q("Anita Sharma") == [d2["id"]]                   # every word must be present
    assert q("Anita Verma") == [d2["id"]]                    # words may be in different places
    assert q("Anita Zebra") == []
    # titles/case fields are ordinary columns and keep substring matching
    assert d1["id"] in q("theft") and q("Witness statement Ani") == [d2["id"]]


def _semantic_ai(world, vectors: dict[str, list[float]]):
    """AI double: embedding chosen by a keyword in the text, so the tests control what is 'similar'."""
    import httpx

    from app.ai.http_client import HttpAI

    def pick(text: str) -> list[float]:
        for word, vec in vectors.items():
            if word in text.lower():
                return vec
        return [0.0, 0.0, 1.0]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/ai/embed":
            import json as _j
            return httpx.Response(200, json={"vectors": [pick(_j.loads(req.content)["texts"][0])]})
        # /ai/process: read the uploaded text back out of the multipart body
        body = req.content.decode("utf-8", "ignore")
        return httpx.Response(200, json={
            "ocr": {"text": body, "language": "eng", "confidence": 0.9, "method": "t", "pages": [1], "needs_review": False},
            "classification": {"doc_type": "other", "confidence": 0.5, "scores": {}}, "entities": {}, "tags": [],
            "embedding": pick(body), "engine": "sem-test"})

    world.app.state.ai = HttpAI("http://ai.local", "k", transport=httpx.MockTransport(handler))


def test_semantic_search_ranks_by_meaning_within_permissions(world):
    _semantic_ai(world, {"theft": [1.0, 0.0, 0.0], "fraud": [0.0, 1.0, 0.0]})
    c1 = world.make_case("officer1")
    c2 = world.make_case("officer2", title="Other case")
    a = world.upload(c1["id"], data=b"motorcycle theft near the market", name="a.txt", title="Doc A")
    b = world.upload(c1["id"], data=b"online fraud on a bank account", name="b.txt", title="Doc B")
    c = world.upload(c2["id"], "officer2", data=b"another theft, this one in a different case", name="c.txt", title="Doc C")

    r = world.client.get("/api/search", headers=world.h("officer1"), params={"q": "stolen bike and theft", "semantic": "true"})
    assert r.status_code == 200 and r.json()["mode"] == "semantic"
    ids = [d["document_id"] for d in r.json()["documents"]]
    assert ids == [a["id"]]                                  # Doc B is unrelated (below threshold); Doc C is not theirs
    assert r.json()["documents"][0]["score"] > 0.99
    r2 = world.client.get("/api/search", headers=world.h("officer2"), params={"q": "theft", "semantic": "true"})
    assert [d["document_id"] for d in r2.json()["documents"]] == [c["id"]]


def test_semantic_search_requires_a_query_and_an_ai_service(world):
    _setup(world)
    h = world.h("officer1")
    assert world.client.get("/api/search", headers=h, params={"semantic": "true"}).status_code == 422
    # built-in stub cannot embed -> honest 503 instead of silently returning keyword results
    assert world.client.get("/api/search", headers=h, params={"q": "theft", "semantic": "true"}).status_code == 503


def test_search_is_audited(world):
    _setup(world)
    world.client.get("/api/search", headers=world.h("officer1"), params={"q": "Rampur"})
    ev = [e for e in world.audit_actions(action="SEARCH") if e["detail"]["params"].get("q") == "Rampur"]
    assert ev and ev[0]["detail"]["documents"] == 1
