"""UAT Test 1: ExtractedFact minimal creation."""
from osint_system.data_management.schemas import ExtractedFact, Claim


def test():
    f = ExtractedFact(claim=Claim(text='Test'))
    print(f.fact_id[:8], f.content_hash[:16])
    assert len(f.fact_id) == 36, "fact_id should be UUID"
    assert len(f.content_hash) == 64, "content_hash should be SHA256"
    print("PASS")


if __name__ == "__main__":
    test()
