"""UAT Test 4: Content hash deduplication."""
from osint_system.data_management.schemas import ExtractedFact, Claim


def test():
    f1 = ExtractedFact(claim=Claim(text='Same claim'))
    f2 = ExtractedFact(claim=Claim(text='Same claim'))
    print(f1.content_hash == f2.content_hash)
    assert f1.content_hash == f2.content_hash, "Same text should produce same hash"
    print("PASS")


if __name__ == "__main__":
    test()
