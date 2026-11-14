"""Block hooks: the door to and from Claude Code's hooks. A hook's JSON becomes an event and a verdict becomes its
answer (io.py); the answers of a form are read from the PostToolUse the model cannot write (forms.py). It decides nothing."""
ITEMS = [
    {"kind": "hook", "name": "hook_io", "ref": "harness.hooks.io:HookIO"},
    {"kind": "translator", "name": "answers", "ref": "harness.hooks.forms:Answers"},
]
