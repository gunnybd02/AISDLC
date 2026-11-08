"""Skills: the library of skills, one folder each with a SKILL.md that starts with a frontmatter of name and
description. Claude Code does not list it; find and guide serve it."""
import re
from dataclasses import dataclass
from pathlib import Path

FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    text: str


class Skills:
    def __init__(self, skills_dir):
        self.dir = Path(skills_dir)

    def all(self):
        return [Skills.read(p) for p in sorted(self.dir.glob("*/SKILL.md"))]

    def get(self, name):
        return next((s for s in self.all() if s.name == name), None)

    @staticmethod
    def read(path):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        m = FRONT.match(text)
        fields = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M)) if m else {}
        if not fields.get("name") or not fields.get("description"):
            raise SkillError(f"{path}: a skill starts with a frontmatter of name and description")
        return Skill(fields["name"], fields["description"], text)
