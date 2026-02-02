"""UAT Test 7: ExtractionPipeline initialization."""
from osint_system.pipelines import ExtractionPipeline


def test():
    p = ExtractionPipeline()
    print(p.batch_size)
    assert p.batch_size == 10, f"Expected batch_size=10, got {p.batch_size}"
    print("PASS")


if __name__ == "__main__":
    test()
