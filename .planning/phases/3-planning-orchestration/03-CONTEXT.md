# Phase 3: Planning & Orchestration Agent - Context

**Gathered:** 2026-01-12
**Status:** Ready for research

<vision>
## How This Should Work

The Planning & Orchestration Agent operates like a research coordinator. When given an objective, it understands the question deeply, then orchestrates an iterative refinement process.

It doesn't just create a static plan and execute — it makes initial queries, reviews what agents discover, adjusts its approach, and digs deeper where promising signals emerge. The agent transparently shows its thinking, explaining how it's breaking down the objective and why it's making certain decisions.

As information flows in from various agents, the Planning Agent provides regular status updates on what agents are doing and what it's learning. For complex investigations, it can create hierarchical delegation structures — particularly splitting coordination by source type (news sub-coordinator, social media sub-coordinator, document sub-coordinator).

When contradictory information emerges, the agent tracks all versions without premature judgment, maintaining the full spectrum of perspectives for later analysis.

</vision>

<essential>
## What Must Be Nailed

- **Adaptive coordination** - The system must dynamically adjust its plan based on what agents discover, not rigidly follow a predetermined path
- **Iterative refinement** - Must be able to recognize promising leads and dig deeper, while also knowing when to stop based on diminishing returns
- **Transparency** - The agent must show its reasoning and provide regular status updates

</essential>

<boundaries>
## What's Out of Scope

- Actual data collection - The Planning Agent purely orchestrates, it doesn't crawl or fetch data itself
- Performance optimization - Focus on working coordination patterns, not speed or efficiency optimizations
- Fact extraction/classification - The Planning Agent coordinates these activities but doesn't perform them

</boundaries>

<specifics>
## Specific Ideas

- **Show its thinking**: The agent should explain its reasoning about how it's breaking down objectives and making decisions
- **Status updates**: Regular updates on what agents are doing and what the system is learning
- **Hierarchical delegation**: Can create sub-coordinators, particularly split by source type (news, social media, documents)
- **Refinement triggers**: Pursue strong relevance signals, ensure diverse coverage, stop based on diminishing returns
- **Conflict handling**: Track all conflicting versions of information without immediate resolution

</specifics>

<notes>
## Additional Context

The user emphasized the research coordinator mental model over project manager or detective chief approaches. The key differentiator is the iterative, adaptive nature — learning and adjusting as investigation proceeds rather than following a fixed plan.

The combination of signal strength, coverage goals, and diminishing returns for deciding when to refine vs move on shows sophisticated thinking about research efficiency.

The choice to track all conflicting information rather than immediately resolve or weight by source indicates a preference for maintaining objectivity and completeness in the intelligence gathering process.

</notes>

---

*Phase: 03-planning-orchestration*
*Context gathered: 2026-01-12*