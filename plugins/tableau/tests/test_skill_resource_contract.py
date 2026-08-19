import json
from pathlib import Path
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "scripts" / "tableau_resources.py"

SKILL_NAMES = ("tableau-workbook-authoring", "tableau-pulse-insights")


def _skill_path(skill_name: str) -> Path:
    return PLUGIN / "skills" / skill_name / "SKILL.md"


def _read_frontmatter(text: str) -> dict[str, str]:
    """Parse a minimal ``key: value`` YAML frontmatter block, stdlib only."""
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md must open with a '---' frontmatter fence")
    end = text.index("\n---", 4)
    frontmatter: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise AssertionError(f"Malformed frontmatter line: {line!r}")
        frontmatter[key.strip()] = value.strip()
    return frontmatter


class SkillResourceContractTest(unittest.TestCase):
    def test_frontmatter_declares_skill_name_and_description(self) -> None:
        for skill_name in SKILL_NAMES:
            frontmatter = _read_frontmatter(_skill_path(skill_name).read_text())
            self.assertEqual(frontmatter.get("name"), skill_name)
            self.assertTrue(frontmatter.get("description"))

    def test_skill_relative_cli_path_resolves_to_the_real_script(self) -> None:
        for skill_name in SKILL_NAMES:
            text = _skill_path(skill_name).read_text()
            self.assertIn("../../scripts/tableau_resources.py", text)
            skill_dir = _skill_path(skill_name).parent
            resolved = (skill_dir / "../../scripts/tableau_resources.py").resolve()
            self.assertEqual(resolved, SCRIPT.resolve())
            self.assertTrue(resolved.is_file())

    def test_authoring_skill_documents_every_cli_command_with_real_flags(self) -> None:
        authoring = _skill_path("tableau-workbook-authoring").read_text()
        for command in ("list", "inspect", "instantiate", "inject", "validate"):
            self.assertIn(f"tableau_resources.py {command}", authoring)
        for flag in (
            "--datasource-definition",
            "--worksheet-name",
            "--map",
            "--param",
            "--datasource ",
            "--input",
        ):
            self.assertIn(flag, authoring)

    def test_authoring_skill_orders_local_validate_before_package_gate_before_publish(
        self,
    ) -> None:
        authoring = _skill_path("tableau-workbook-authoring").read_text()
        local_validate = authoring.index("Run `validate`")
        package_gate = authoring.index("validate-workbook-package")
        publish = authoring.index("Publish only")
        self.assertLess(local_validate, package_gate)
        self.assertLess(package_gate, publish)

    def test_pulse_skill_scopes_discovery_to_family_and_delegates(self) -> None:
        pulse = _skill_path("tableau-pulse-insights").read_text()
        self.assertIn("--family pulse-insights", pulse)
        self.assertIn("--tier executable", pulse)
        self.assertIn("tableau-workbook-authoring", pulse)

    def test_plugin_prompts_surface_template_authoring(self) -> None:
        plugin = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        prompts = plugin["interface"]["defaultPrompt"]
        self.assertIn("Build a Tableau workbook from a template", prompts)


class ValidationSemanticsDocumentationTest(unittest.TestCase):
    """Fix Round 1: standalone `validate` is absolute; delta is scoped to inject."""

    def setUp(self) -> None:
        self.guide = (
            PLUGIN / "skills/tableau-workbook-authoring/references/resource-guide.md"
        ).read_text()
        self.authoring = _skill_path("tableau-workbook-authoring").read_text()
        self.package_gate = (
            PLUGIN / "skills/validate-workbook-package/SKILL.md"
        ).read_text()

    def _section(self, heading: str, next_heading: str) -> str:
        return self.guide.split(heading, 1)[1].split(next_heading, 1)[0]

    def test_standalone_validate_is_documented_as_absolute_not_delta(self) -> None:
        validate_section = self._section("## `validate`", "## Failure recovery")
        self.assertIn("absolute", validate_section.lower())
        # A cross-reference to inject's delta behavior is fine; claiming
        # the standalone command itself is a delta check is not.
        self.assertNotIn("is a delta", validate_section.lower())
        self.assertNotIn(
            "delta check against the input workbook", self.authoring.lower()
        )

    def test_delta_behavior_is_scoped_to_inject_and_instantiate_uses_clean_baseline(
        self,
    ) -> None:
        inject_section = self._section("## `inject`", "## `validate`")
        self.assertIn("delta", inject_section.lower())
        instantiate_section = self._section("## `instantiate`", "## `inject`")
        self.assertTrue(
            "baseline" in instantiate_section.lower()
            or "starter" in instantiate_section.lower()
        )

    def test_package_gate_prerequisite_is_absolute_not_delta(self) -> None:
        self.assertIn("absolute structural check", self.package_gate)
        # A cross-reference to inject's own delta check is fine; claiming
        # local resource validation itself is a delta check is not.
        self.assertNotIn("structural delta check", self.package_gate)

    def test_validate_documents_exit_code_2_for_operational_errors(self) -> None:
        validate_section = self._section("## `validate`", "## Failure recovery")
        self.assertIn("exit code `2`", validate_section.lower())

    def test_inject_datasource_is_documented_as_internal_name_not_invented_command(
        self,
    ) -> None:
        self.assertNotIn("inspect-datasources", self.guide)
        inject_section = self._section("## `inject`", "## `validate`")
        self.assertIn("internal", inject_section.lower())
        self.assertIn("<datasources>", inject_section)
        self.assertIn("Workbook has no datasource named", inject_section)

    def test_reference_guide_states_paths_are_relative_to_skill_directory(
        self,
    ) -> None:
        self.assertIn("skill's own directory", self.guide)
        self.assertIn("absolute path", self.guide)

    def test_primary_inject_example_uses_a_distinct_output_path(self) -> None:
        inject_section = self._section("## `inject`", "## `validate`")
        first_example = inject_section.split("```bash", 1)[1].split("```", 1)[0]
        self.assertIn("--input ./workbook.twb", first_example)
        self.assertNotIn("--output ./workbook.twb", first_example)
        self.assertIn("deliberate", inject_section.lower())

    def test_map_and_param_parsing_rules_are_documented(self) -> None:
        self.assertIn("stripped", self.guide.lower())
        self.assertIn("duplicate", self.guide.lower())
        self.assertIn("blank", self.guide.lower())


if __name__ == "__main__":
    unittest.main()
