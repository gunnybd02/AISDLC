"""Skills: the library of skills, one folder each with a SKILL.md that starts with a frontmatter of name and
description; the name is the folder's. Claude Code does not list it; find and guide serve it."""
import re
from dataclasses import dataclass
from pathlib import Path

FRONT = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.S)


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

    def paths(self):
        return sorted(self.dir.glob("*/SKILL.md"))

    def all(self):
        """The skills that read; one that does not is left out here, so it hides no other (problems() names it)."""
        out = []
        for path in self.paths():
            try:
                out.append(Skills.read(path))
            except SkillError:
                continue
        return out

    def get(self, name):
        return next((s for s in self.all() if s.name == name), None)

    def problems(self):
        """Each skill that does not read, whose name is not its folder's, or whose name another skill has."""
        out, seen = [], {}
        for path in self.paths():
            rel = path.relative_to(self.dir).as_posix()
            try:
                skill = Skills.read(path)
            except SkillError as e:
                out.append(f"skill {rel}: {e}")
                continue
            if skill.name != path.parent.name:
                out.append(f"skill {rel}: its name {skill.name} is not its folder {path.parent.name}")
            if skill.name in seen:
                out.append(f"skill {rel}: the name {skill.name} is used twice (also {seen[skill.name]})")
            seen[skill.name] = rel
        return out

    @staticmethod
    def read(path):
        try:
            text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        except UnicodeDecodeError as e:
            raise SkillError(f"does not decode as UTF-8 ({e.reason})") from e
        m = FRONT.match(text)
        fields = dict(re.findall(r"^(\w+):[ \t]*(.*)$", m.group(1), re.M)) if m else {}
        if not fields.get("name") or not fields.get("description"):
            raise SkillError("a skill starts with a frontmatter of name and description")
        return Skill(fields["name"], fields["description"], text)
