from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

GLOBAL_SKILLS_DIR = Path.home() / ".gitsage" / "skills"
PROJECT_SKILLS_DIR_NAME = ".gitsage/skills"

@dataclass
class Skill:
    name: str
    description: str
    content: str      # full SKILL.md content (without frontmatter)
    path: Path
    trigger: str = "auto"  # auto | manual

class SkillLoader:
    """Loads SKILL.md files from project and global directories."""

    def __init__(self, repo_path: Path = None):
        self._repo_path = repo_path or Path.cwd()
        self._project_skills = self._repo_path / PROJECT_SKILLS_DIR_NAME
        self._global_skills = GLOBAL_SKILLS_DIR

    def load(self, skill_name: str) -> Skill | None:
        """Load a specific skill by name. Project skills override global."""
        for skills_dir in [self._project_skills, self._global_skills]:
            skill_file = skills_dir / skill_name / "SKILL.md"
            if skill_file.exists():
                return self._parse_skill(skill_file)
        return None

    def load_all(self) -> list[Skill]:
        """Load all available skills."""
        skills = {}
        for skills_dir in [self._global_skills, self._project_skills]:
            if not skills_dir.exists():
                continue
            for skill_dir in skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skill = self._parse_skill(skill_file)
                        if skill:
                            skills[skill.name] = skill  # project overrides global
        return list(skills.values())

    def _parse_skill(self, path: Path) -> Skill | None:
        try:
            content = path.read_text(encoding="utf-8")
            name, description, trigger, body = self._parse_frontmatter(content, path)
            return Skill(name=name, description=description, content=body, path=path, trigger=trigger)
        except Exception:
            return None

    def _parse_frontmatter(self, content: str, path: Path) -> tuple:
        """Parse YAML frontmatter from SKILL.md."""
        import re
        name = path.parent.name
        description = ""
        trigger = "auto"
        body = content

        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
        if fm_match:
            fm_text, body = fm_match.group(1), fm_match.group(2)
            for line in fm_text.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
                elif line.startswith("trigger:"):
                    trigger = line.split(":", 1)[1].strip()
        return name, description, trigger, body
