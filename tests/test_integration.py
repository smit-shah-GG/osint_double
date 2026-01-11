"""Integration test for the complete multi-agent architecture.

This test validates that all components work together:
- MessageBus for communication
- AgentRegistry for discovery
- SimpleAgent instances
- Coordinator with LangGraph supervisor
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from osint_system.communication.message_bus import MessageBus
from osint_system.communication.registry import AgentRegistry
from osint_system.agents.base_agent import BaseAgent
from osint_system.orchestration.coordinator import Coordinator


class SimpleAgent(BaseAgent):
    """Simple test agent implementation."""

    def __init__(self, agent_id: str, capabilities: list[str]):
        """Initialize test agent with given capabilities."""
        super().__init__(agent_id, "simple_agent")
        self._capabilities = capabilities
        self.received_messages = []

    async def process_message(self, message: dict) -> dict:
        """Process a message and return response."""
        self.received_messages.append(message)
        return {
            "status": "processed",
            "agent_id": self.agent_id,
            "message_type": message.get("type", "unknown"),
            "content": f"Processed by {self.agent_id}"
        }

    def get_capabilities(self) -> list[str]:
        """Return agent capabilities."""
        return self._capabilities

    async def execute_task(self, task: str, context: dict = None) -> dict:
        """Execute a task."""
        return {
            "status": "completed",
            "agent_id": self.agent_id,
            "task": task,
            "result": f"Task '{task}' completed by {self.agent_id}"
        }


async def test_agent_registration():
    """Test that agents can register and discover each other."""
    print("\n[TEST] Agent Registration and Discovery")
    print("=" * 50)

    # Create message bus and registry
    bus = MessageBus()
    registry = AgentRegistry(bus)

    # Create two test agents
    agent1 = SimpleAgent("test_agent_1", ["search", "extract"])
    agent2 = SimpleAgent("test_agent_2", ["analyze", "verify"])

    # Register agents
    await registry.register(agent1)
    await registry.register(agent2)

    # Test discovery
    all_agents = registry.get_all_agents()
    assert len(all_agents) == 2, f"Expected 2 agents, got {len(all_agents)}"
    print(f"✓ Successfully registered {len(all_agents)} agents")

    # Test capability lookup
    search_agents = registry.find_by_capability("search")
    assert len(search_agents) == 1, f"Expected 1 search agent, got {len(search_agents)}"
    assert search_agents[0].agent_id == "test_agent_1"
    print("✓ Capability-based lookup working")

    analyze_agents = registry.find_by_capability("analyze")
    assert len(analyze_agents) == 1, f"Expected 1 analyze agent, got {len(analyze_agents)}"
    assert analyze_agents[0].agent_id == "test_agent_2"
    print("✓ Multiple capability types supported")

    return True


async def test_message_passing():
    """Test message passing between agents via the bus."""
    print("\n[TEST] Message Passing")
    print("=" * 50)

    # Create infrastructure
    bus = MessageBus()
    registry = AgentRegistry(bus)

    # Create and register agents
    agent1 = SimpleAgent("sender", ["send"])
    agent2 = SimpleAgent("receiver", ["receive"])

    await registry.register(agent1)
    await registry.register(agent2)

    # Subscribe agent2 to a channel
    callback_triggered = False
    received_data = None

    async def message_callback(data):
        nonlocal callback_triggered, received_data
        callback_triggered = True
        received_data = data

    await bus.subscribe("test_channel", message_callback)

    # Agent1 publishes a message
    test_message = {
        "type": "test",
        "from": "sender",
        "to": "receiver",
        "content": "Hello, Agent2!"
    }
    await bus.publish("test_channel", test_message)

    # Give async operations time to complete
    await asyncio.sleep(0.1)

    assert callback_triggered, "Message callback was not triggered"
    assert received_data == test_message, "Received data doesn't match sent message"
    print("✓ Messages successfully passed via bus")

    return True


async def test_coordinator_workflow():
    """Test the Coordinator's ability to manage workflows."""
    print("\n[TEST] Coordinator Workflow Management")
    print("=" * 50)

    # Create infrastructure
    bus = MessageBus()
    registry = AgentRegistry(bus)

    # Create specialized agents
    crawler = SimpleAgent("crawler_1", ["crawl", "fetch"])
    sifter = SimpleAgent("sifter_1", ["extract", "classify"])
    reporter = SimpleAgent("reporter_1", ["analyze", "report"])

    # Register all agents
    for agent in [crawler, sifter, reporter]:
        await registry.register(agent)

    # Create coordinator
    coordinator = Coordinator(registry, bus)

    # Test supervisor decision making
    print("Testing supervisor routing...")

    # Simulate a crawl request
    crawl_result = await coordinator.route_task(
        task="crawl",
        context={"url": "https://example.com"}
    )

    assert crawl_result["next_agent"] == "crawler_1", \
        f"Expected crawler_1, got {crawl_result.get('next_agent')}"
    print(f"✓ Supervisor correctly routed to {crawl_result['next_agent']}")

    # Simulate an extract request
    extract_result = await coordinator.route_task(
        task="extract",
        context={"text": "Sample text to extract facts from"}
    )

    assert extract_result["next_agent"] == "sifter_1", \
        f"Expected sifter_1, got {extract_result.get('next_agent')}"
    print(f"✓ Supervisor correctly routed to {extract_result['next_agent']}")

    # Test workflow graph construction
    print("\nTesting workflow graph construction...")
    workflow_created = coordinator._build_workflow()
    assert workflow_created is not None, "Workflow graph was not created"
    print("✓ Workflow graph successfully built")

    return True


async def test_end_to_end_flow():
    """Test a complete end-to-end agent interaction flow."""
    print("\n[TEST] End-to-End Agent Interaction")
    print("=" * 50)

    # Create full system
    bus = MessageBus()
    registry = AgentRegistry(bus)

    # Create a chain of agents
    agents = [
        SimpleAgent("fetcher", ["fetch_data"]),
        SimpleAgent("processor", ["process_data"]),
        SimpleAgent("validator", ["validate_results"]),
    ]

    for agent in agents:
        await registry.register(agent)

    # Create coordinator
    coordinator = Coordinator(registry, bus)

    # Execute a multi-step workflow
    print("Executing multi-step workflow...")

    steps = [
        ("fetch_data", {"source": "test_source"}),
        ("process_data", {"format": "json"}),
        ("validate_results", {"schema": "test_schema"}),
    ]

    results = []
    for task, context in steps:
        result = await coordinator.route_task(task, context)
        results.append(result)
        expected_agent = {
            "fetch_data": "fetcher",
            "process_data": "processor",
            "validate_results": "validator"
        }[task]

        assert result["next_agent"] == expected_agent, \
            f"Task {task} routed to {result.get('next_agent')}, expected {expected_agent}"
        print(f"  ✓ Step '{task}' → {expected_agent}")

    print("✓ Multi-step workflow completed successfully")

    # Verify all agents were utilized
    utilized_agents = set(r["next_agent"] for r in results)
    assert len(utilized_agents) == 3, f"Expected 3 unique agents, got {len(utilized_agents)}"
    print(f"✓ All {len(utilized_agents)} agents participated in workflow")

    return True


async def main():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print(" OSINT System Integration Test Suite")
    print("=" * 60)

    tests = [
        ("Agent Registration", test_agent_registration),
        ("Message Passing", test_message_passing),
        ("Coordinator Workflow", test_coordinator_workflow),
        ("End-to-End Flow", test_end_to_end_flow),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            result = await test_func()
            if result:
                passed += 1
                print(f"\n[PASSED] {test_name}")
            else:
                failed += 1
                print(f"\n[FAILED] {test_name}")
        except Exception as e:
            failed += 1
            print(f"\n[FAILED] {test_name}: {str(e)}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f" Results: {passed} PASSED, {failed} FAILED")
    print("=" * 60)

    if failed == 0:
        print("\n🎉 All tests PASSED! The multi-agent architecture is working!")
        sys.exit(0)
    else:
        print(f"\n❌ {failed} test(s) failed. Please review the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())