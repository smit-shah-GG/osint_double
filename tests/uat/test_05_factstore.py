"""UAT Test 5: FactStore save and retrieve."""
import pytest
from osint_system.data_management.fact_store import FactStore


@pytest.mark.asyncio
async def test():
    s = FactStore()
    await s.save_facts('inv1', [{'fact_id': 'f1', 'content_hash': 'h1', 'claim': {'text': 'T'}}])
    result = await s.get_fact('inv1', 'f1')
    print(result['fact_id'])
    assert result['fact_id'] == 'f1', f"Expected 'f1', got {result['fact_id']}"
    print("PASS")
