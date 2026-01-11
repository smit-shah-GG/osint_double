"""Simplified integration test that works with actual API."""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from osint_system.agents.communication.bus import MessageBus
from osint_system.agents.registry import AgentRegistry
from osint_system.orchestration.coordinator import Coordinator


async def test_basic_components():
    """Test that basic components can be created."""
    print("\n[TEST] Basic Components")
    print("=" * 50)

    # Test MessageBus creation
    bus = MessageBus()
    assert bus is not None, "MessageBus creation failed"
    print("✓ MessageBus created successfully")

    # Test AgentRegistry creation
    registry = AgentRegistry()
    assert registry is not None, "AgentRegistry creation failed"
    print("✓ AgentRegistry created successfully")

    # Test Coordinator creation
    coordinator = Coordinator()
    assert coordinator is not None, "Coordinator creation failed"
    print("✓ Coordinator created successfully")

    return True


async def test_agent_registration():
    """Test basic agent registration."""
    print("\n[TEST] Agent Registration")
    print("=" * 50)

    registry = AgentRegistry()

    # Register an agent
    agent_id = await registry.register_agent(
        name="test_agent",
        capabilities=["search", "extract"]
    )
    assert agent_id is not None, "Agent registration failed"
    print(f"✓ Agent registered with ID: {agent_id}")

    # Find agent by capability
    agents = await registry.find_agents_by_capability("search")
    assert len(agents) == 1, f"Expected 1 agent with 'search', got {len(agents)}"
    print("✓ Agent found by capability")

    return True


async def test_message_bus():
    """Test basic message bus functionality."""
    print("\n[TEST] Message Bus")
    print("=" * 50)

    bus = MessageBus()

    # Test message publishing (basic smoke test)
    try:
        message = {"type": "test", "content": "Hello"}
        # The publish method exists based on the bus.py file
        await bus.publish("test_channel", message)
        print("✓ Message published successfully")
    except Exception as e:
        print(f"✗ Message publishing failed: {e}")
        return False

    return True


async def test_coordinator_init():
    """Test coordinator initialization."""
    print("\n[TEST] Coordinator Initialization")
    print("=" * 50)

    coordinator = Coordinator()

    # Test that coordinator has expected components
    assert hasattr(coordinator, 'registry'), "Coordinator missing registry"
    assert hasattr(coordinator, 'message_bus'), "Coordinator missing message_bus"
    print("✓ Coordinator has registry and message_bus")

    # Test coordinator initialization
    try:
        await coordinator.initialize()
        print("✓ Coordinator initialized successfully")
    except Exception as e:
        print(f"✗ Coordinator initialization failed: {e}")
        return False

    return True


async def test_mcp_server_import():
    """Test that MCP server can be imported."""
    print("\n[TEST] MCP Server Import")
    print("=" * 50)

    try:
        from osint_system.tools.mcp_server import server
        assert server is not None, "MCP server not found"
        print("✓ MCP server module imported successfully")
    except Exception as e:
        print(f"✗ MCP server import failed: {e}")
        return False

    return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print(" OSINT System Integration Test Suite (Simplified)")
    print("=" * 60)

    tests = [
        ("Basic Components", test_basic_components),
        ("Agent Registration", test_agent_registration),
        ("Message Bus", test_message_bus),
        ("Coordinator Initialization", test_coordinator_init),
        ("MCP Server Import", test_mcp_server_import),
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

    print("\n" + "=" * 60)
    print(f" Results: {passed} PASSED, {failed} FAILED")
    print("=" * 60)

    if failed == 0:
        print("\n🎉 All tests PASSED! Core components are working!")
        sys.exit(0)
    else:
        print(f"\n❌ {failed} test(s) failed.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())