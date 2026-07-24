# Open a project — grounding fires automatically

1. Open a folder that has (or will have) a factbook under `.nora/`.
2. From a terminal in that folder:

```bash
kernora generate
```

That emits steering files (`CLAUDE.md`, `.cursorrules`, and related surfaces) from your factbook.

On relevant turns, Nora injects matching factlets **before** the model writes — ambient grounding, no `+nora` prefix required. If the factbook does not cover the prompt, the relevance gate stays silent.
