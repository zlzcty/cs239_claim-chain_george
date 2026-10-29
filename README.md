# Claim Chain Auditor

A proposed class project that audits a claim by following citations, inspecting the referenced passages, and reporting what the available evidence supports. A Research Lead assigns bounded questions to Investigators, and a separate Review Agent checks the draft against the evidence.

The repository currently contains design documents and a Python project scaffold. The auditor, providers, fixtures, and agent runtime are not implemented; the scaffold's `repo` command only prints a placeholder message.

- [app.md](app.md): application purpose and supported tasks
- [policy.md](policy.md): rules for agents during execution
- [agents/](agents/): role system prompts and available tools
- [protocol.md](protocol.md): communication protocols and rules
- [agent-execution.md](agent-execution.md): Everything about how agents running that doesn't fit in protocol.md:  role permissions, model loop, and provider records
- [evidence.md](evidence.md): source identity, located passages, graph, and snapshots.
- [tools.md](tools.md): tool and tool calls
- [evaluation.md](evaluation.md): planned replayable fixtures and single-agent comparison.

The intended first implementation is a local, single-process workflow using fixture documents and SQLite. A2A can be added through an adapter if required by the course. No setup or demonstration instructions are provided yet because that workflow has not been built.
