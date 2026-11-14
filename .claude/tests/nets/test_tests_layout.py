"""Tests sit in tests/<block>/ and are named after a module of that block: tests/<block>/test_<module>.py tests
harness/<block>/**/<module>.py. tests/nets/ tests the nets, tests/e2e/ runs the entries."""
import unittest

from tests import CLAUDE_DIR

BLOCKS = ("hooks", "gear", "mcp", "assemble", "utils")
OTHERS = ("nets", "e2e")
NAMED = {"mcp/test_action_registry.py"}  # the registry pin, by the name docs/mcp.md gives it


def problems(claude_dir):
    out = []
    for path in sorted((claude_dir / "tests").rglob("test_*.py")):
        rel = path.relative_to(claude_dir / "tests")
        if len(rel.parts) != 2:
            out.append(f"tests/{rel.as_posix()}: a test sits right in tests/<block>/")
            continue
        folder, module = rel.parts[0], rel.stem[len("test_"):]
        if folder in OTHERS or rel.as_posix() in NAMED:
            continue
        if folder not in BLOCKS:
            out.append(f"tests/{rel.as_posix()}: {folder} is no block ({', '.join(BLOCKS + OTHERS)})")
        elif not any((claude_dir / "harness" / folder).rglob(f"{module}.py")):
            out.append(f"tests/{rel.as_posix()}: harness/{folder}/ has no module {module}.py")
    return out


class TestsLayoutTest(unittest.TestCase):
    def test_each_test_file_is_named_after_a_module_of_its_block(self):
        self.assertEqual(problems(CLAUDE_DIR), [])


if __name__ == "__main__":
    unittest.main()
