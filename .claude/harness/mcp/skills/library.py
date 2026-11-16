"""Skills: the library of skills, one folder each with a SKILL.md that starts with a frontmatter of name and
description; the name is the folder's. Claude Code does not list it; find and guide serve it. A skill names what it
uses as the model calls it: run("block", "action", ...), guide("block", "mcp"), guide("skill", "skills"); stale() names
each that is not there, so a skill does not outlive the thing it teaches."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

FRONT = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.S)
RUN = re.compile(r"""\brun\(\s*["'](\w+)["']\s*,\s*["'](\w+)["']""")
GUIDE = re.compile(r"""\bguide\(\s*["']([\w-]+)["']\s*,\s*["'](skills|mcp)["']""")


class SkillError(ValueError):
    """A SKILL.md that does not read: not UTF-8, or no frontmatter of name and description."""


@dataclass(frozen=True)
class Skill:
    """One skill: its name and description (from its frontmatter) and its whole text."""
    name: str
    description: str
    text: str


class Skills:
    """The library of skills: one folder each under skills_dir, with its SKILL.md."""

    def __init__(self, skills_dir: str | Path) -> None:
        """Keep the library's folder.

        Args:
            skills_dir: the folder of the skills (harness/mcp/skill_docs).
        """
        self.dir = Path(skills_dir)

    def paths(self) -> list[Path]:
        """The SKILL.md of each folder of the library.

        Returns:
            Their paths, sorted.
        """
        return sorted(self.dir.glob("*/SKILL.md"))

    def all(self) -> list[Skill]:
        """The skills that read; one that does not is left out here, so it hides no other (problems() names it).

        Returns:
            The skills in the order of their paths.
        """
        out = []
        for path in self.paths():
            try:
                out.append(Skills.read(path))
            except SkillError:
                continue
        return out

    def get(self, name: Optional[str]) -> Optional[Skill]:
        """The skill of that name.

        Args:
            name: the skill's name as the model gave it (None when it gave none).

        Returns:
            The first skill that reads with that name, or None.
        """
        return next((s for s in self.all() if s.name == name), None)

    def problems(self) -> list[str]:
        """Each skill that does not read, whose name is not its folder's, or whose name another skill has.

        Returns:
            One line per problem: "skill <folder>/SKILL.md: <why>".
        """
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

    def stale(self, actions: Iterable[str]) -> list[str]:
        """Each action, block or skill a skill names that is not there; actions are the "block.name" of the server.

        Args:
            actions: the "block.name" of every action of the server.

        Returns:
            One line per missing thing a skill names: "skill <name>: names <what>, which is not there".
        """
        actions, out = set(actions), []
        blocks, names = {a.split(".")[0] for a in actions}, {s.name for s in self.all()}
        for skill in self.all():
            said = [f"the action {b}.{n}" for b, n in RUN.findall(skill.text) if f"{b}.{n}" not in actions]
            said += [f"the {'skill' if mode == 'skills' else 'block'} {name}" for name, mode in GUIDE.findall(skill.text)
                     if name not in (names if mode == "skills" else blocks)]
            out += [f"skill {skill.name}: names {what}, which is not there" for what in dict.fromkeys(said)]
        return out

    @staticmethod
    def read(path: Path) -> Skill:
        """Read one SKILL.md.

        Args:
            path: the SKILL.md file.

        Returns:
            The Skill: the name and description of its frontmatter and its text (newlines made \n).

        Raises:
            SkillError: it does not decode as UTF-8, or has no frontmatter of name and description.
        """
        try:
            text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        except UnicodeDecodeError as e:
            raise SkillError(f"does not decode as UTF-8 ({e.reason})") from e
        m = FRONT.match(text)
        fields = dict(re.findall(r"^(\w+):[ \t]*(.*)$", m.group(1), re.M)) if m else {}
        if not fields.get("name") or not fields.get("description"):
            raise SkillError("a skill starts with a frontmatter of name and description")
        return Skill(fields["name"], fields["description"], text)
