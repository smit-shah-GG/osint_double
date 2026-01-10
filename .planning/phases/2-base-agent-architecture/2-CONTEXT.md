# Phase 2: Base Agent Architecture - Context

**Gathered:** 2026-01-11
**Status:** Ready for research

<vision>
## How This Should Work

The agent architecture should function as an autonomous swarm where agents can self-organize and adapt without central control. Agents broadcast their capabilities when they join the system, allowing others to discover them and form teams based on needs. Think of it like a marketplace where agents announce what they can do and what they need.

Agents are long-running services that maintain state and can build relationships over time. They communicate using both patterns: broadcasting via a message bus for discovery and team formation, then establishing direct channels with specific peers for actual collaborative work. This gives us the best of both worlds - easy discovery and efficient collaboration.

When agents need to work together, they simply match capabilities to needs. No complex reputation systems or trust metrics - just straightforward capability matching. If an agent needs raw text, it finds agents that can provide it.

The whole system should have verbose logging so we can see everything agents are thinking and doing, making debugging and understanding the swarm behavior transparent.

</vision>

<essential>
## What Must Be Nailed

All three of these are equally critical - the system won't function without any of them:

- **Dead-simple communication** - Agents can reliably send and receive messages, broadcast their capabilities, and establish direct channels
- **Tool integration works** - Agents can successfully use external tools via MCP (web scrapers, APIs, etc.)
- **Swarm resilience** - The system keeps running even when individual agents fail, other agents can step in

</essential>

<boundaries>
## What's Out of Scope

- **Production robustness** - This phase focuses on proving concepts work, not handling every edge case
- **Complex reputation systems** - Keep it simple with capability matching only
- **Emergent behavior patterns** - Start with explicit broadcasting, emergence can come later
- **Performance optimization** - Get it working first, optimize later

</boundaries>

<specifics>
## Specific Ideas

- **Verbose logging** - Want to see everything agents are thinking and doing for debugging. Every decision, every message, every state change should be visible.
- **Clean abstractions** - Beautiful base classes that make creating new agents trivial. The framework should be a joy to extend.
- **Broadcasting first** - Start with explicit capability broadcasting before adding any emergent patterns
- **Both communication patterns** - Use message bus for discovery, direct channels for collaboration
- **Long-running services** - Agents stay alive and maintain state, not fire-and-forget

</specifics>

<notes>
## Additional Context

The user envisions an autonomous swarm that's self-organizing but not chaotic. The emphasis is on agents that can discover each other, communicate efficiently, and work together without needing central orchestration.

The choice to start with broadcasting over emergence reflects a preference for explicit, debuggable behavior that can be understood and modified easily. The framework should make it trivial to add new agent types later.

The combination of verbose logging and clean abstractions suggests someone who wants both operational visibility and code elegance - a system that's both powerful and maintainable.

</notes>

---

*Phase: 02-base-agent-architecture*
*Context gathered: 2026-01-11*