---
name: harness-skill
description: Develop the harness - write or change a skill, a SKILL.md text that find and guide serve to the model, with its frame, limits and checks.
---
# Harness skill
A skill is one text that tells the model how to do one kind of work. `find` lists it, `guide` reads it.

## When to use
- To teach the model a way of working, instead of a rule file (`.claude/rules/` is refused) or a long prompt.

## Steps
1. One folder, one file: `.claude/harness/mcp/skill_docs/<name>/SKILL.md`. The name is the folder's: lower case,
   words joined with `-`.
2. Start with the frontmatter, two lines of `key: value`:
   ```
   ---
   name: <name>
   description: <one line: what it is for, in the words someone would search with>
   ---
   ```
   `find` ranks a skill by how many words of the request its name and description hold: put the real words there.
3. Then the frame: `# Title` and one line on what it is; `## When to use`; `## Steps` (numbered, each with the exact
   call); tables for what is refused; `## Notes` for the few things that go wrong.
4. Write calls as the model makes them: `run("<block>", "<action>", {args})`, `guide("<skill>", "skills")`,
   `python3 <core>/anchor.py cli ...`. The doctor checks that each action and skill named this way exists.
5. Keep it short: 300 lines at most (the `size` net), and better under 80. One skill, one kind of work.
6. Check: `find("<words>")` lists it, `guide("<name>", "skills")` reads it, the doctor is clean.
7. Add it to the table of the `start` skill.

## Notes
- Say what to do, not the history of why. Facts only: a skill that names a thing the harness does not have is a bug.
- A skill is part of a release: a new or changed skill reaches sessions after it is published
  (`guide("harness-release", "skills")`).
- A skill of a team's own way of working goes here too, beside these.
