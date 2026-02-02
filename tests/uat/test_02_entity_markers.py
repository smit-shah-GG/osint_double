"""UAT Test 2: Entity markers in claim format."""
from osint_system.data_management.schemas import ExtractedFact, Claim, Entity, EntityType


def test():
    f = ExtractedFact(
        claim=Claim(text='[E1:Putin] visited Beijing'),
        entities=[Entity(id='E1', text='Putin', type=EntityType.PERSON)]
    )
    print(f.claim.text)
    assert f.claim.text == '[E1:Putin] visited Beijing'
    print("PASS")


if __name__ == "__main__":
    test()
