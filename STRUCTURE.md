# DevAgent — Project Structure Reference

## Overview

`/root/DevAgent` is the root workspace for a dev agent that manages multiple GitHub projects independently.

## Layout

```
/root/DevAgent/
├── STRUCTURE.md          # This file — workspace rules and layout reference
├── .env                  # Environment variables (e.g. GitHub PAT) — never commit
├── <tool-docs>.md        # Tool and workflow documentation for Claude
└── <project-name>/       # One subfolder per GitHub project (cloned repo)
    └── ...               # Project code only — no agent tooling or metadata here
```

## Rules

1. **Each subfolder is an independent GitHub project.** It maps 1:1 to a GitHub repo and is managed on its own (separate git history, branches, issues, etc.).

2. **Tool docs and metadata live at the DevAgent root only.** Any `.md` reference files, workflow guides, or agent configuration belong at `/root/DevAgent/`, never inside a project subfolder.

3. **Project folders stay clean.** Nothing agent-specific (docs, metadata, memory artifacts) should be written into a project subfolder. Only the project's own code and assets belong there.

4. **Each project is handled separately.** Changes, commits, pushes, and decisions in one project do not affect others.
