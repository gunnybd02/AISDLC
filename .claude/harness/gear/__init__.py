"""Block gear: translate a tool call, detect findings, decide the verdict."""
ITEMS = [
    {"kind": "rule", "name": "decide", "ref": "harness.gear.decide.arbiter:Decide"},
    {"kind": "translator", "name": "places", "ref": "harness.gear.translate.place:Places"},
    {"kind": "translator", "name": "git_commands", "ref": "harness.gear.translate.git:GitCommands"},
    {"kind": "detector", "name": "forms", "ref": "harness.gear.detect.forms:Forms"},
    {"kind": "detector", "name": "tracked", "ref": "harness.gear.detect.tracked:Tracked"},
    {"kind": "detector", "name": "planfiles", "ref": "harness.gear.detect.planfiles:PlanFiles"},
    {"kind": "detector", "name": "raw_commit", "ref": "harness.gear.detect.commit:RawCommit"},
]
