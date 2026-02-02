"""UAT Test 3: FactExtractionAgent initialization."""
from osint_system.agents.sifters import FactExtractionAgent


def test():
    a = FactExtractionAgent(gemini_client=None)
    print(a.name, len(a.get_capabilities()))
    assert a.name == 'FactExtractionAgent'
    assert len(a.get_capabilities()) >= 5, f"Expected at least 5 capabilities, got {len(a.get_capabilities())}"
    print("PASS")


if __name__ == "__main__":
    test()
