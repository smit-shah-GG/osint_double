"""UAT Test 6: FactConsolidator deduplication."""
import pytest
from osint_system.agents.sifters import FactConsolidator


@pytest.mark.asyncio
async def test():
    c = FactConsolidator()
    r = await c.sift({
        'facts': [
            {'fact_id': 'f1', 'claim': {'text': 'Same'}},
            {'fact_id': 'f2', 'claim': {'text': 'Same'}}
        ],
        'investigation_id': 'i1'
    })
    print(len(r))
    assert len(r) == 1, f"Expected 1 deduplicated fact, got {len(r)}"
    print("PASS")
