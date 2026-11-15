---
name: harness-rule
description: Develop the harness - add or change a rule on tool calls, with a translator for facts, a detector for findings, a rule row with its verdict, and its test.
---
# Harness rule
A rule is three small parts and a test: a fact, a finding, a row. Only the arbiter judges.

## When to use
- To make the harness refuse, ask about or see a new kind of tool call, or to change what an existing rule answers.

## Steps
1. Write the test first: `harness/tests/gear/test_<module>.py`, named after the module it tests
   (`harness/tests/nets/test_tests_layout.py` checks the name).
2. The fact, when no translator gives it yet: a class on `Translator` (`utils/contracts.py`) in
   `gear/translate/<module>.py`. `translate(event)` returns a dict of facts and never judges. Each fact has one giver.
3. The finding: a class on `Detector` in `gear/detect/<module>.py`.
   ```python
   from harness.utils.contracts import Detector, Finding

   class NoTabs(Detector):
       def detect(self, event, facts):
           return [Finding("style.tab", facts["path"])] if facts.get("has_tab") else []
   ```
   A detector reports; it never names a verdict (the `verdict` net refuses the words).
4. Declare each class with one line in `gear/__init__.py`:
   `{"kind": "detector", "name": "no_tabs", "ref": "harness.gear.detect.style:NoTabs"}`. A name is used once.
5. Name it in the pipeline: `assemble/pipelines/base.json`, under `translators` or `detectors`.
6. The row, in `gear/rules/<file>.json` (`place.json`: edits, reads, the shell; `git.json`: git and commits;
   `actions.json`: write actions):
   ```json
   {"finding": "style.tab", "verdict": "refuse", "why": "<what to do instead, for the model>",
    "test": "harness/tests/gear/test_style.py#test_a_tab_is_refused"}
   ```
   The verdict is `allow`, `ask` or `refuse`; the strongest of a call's findings wins. A row whose test does not
   exist does not load. A finding with no row asks the user.
7. Run the tests and the doctor until both are clean: `guide("harness-map", "skills")`.

## Writing the why
- The model reads it when the call is refused: say what to do instead, with the exact action or command.
- When it names an action as `run('<block>', '<action>', ...)`, the harness adds how to call it from the shell.
- Add the finding to the tables of the `refused` skill.

## Notes
- Facts from outside (the ledger, git) come through a port: `assemble/engine/ports.py`.
- The shell reader (`utils/shell/`) turns a command into the files it writes; a rule on shell lines starts there.
- To change only what a rule answers, change its row and its test; the detector stays.
