"""Block gear: translate a tool call, detect findings, decide the verdict."""
ITEMS = [
    {"kind": "rule", "name": "decide", "ref": "harness.gear.decide:Decide"},
    {"kind": "translator", "name": "answers", "ref": "harness.gear.translate_answer:Answers"},
]
