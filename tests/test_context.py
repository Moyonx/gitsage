"""Tests for gitsage context modules: ctx_reader, memory, skills/loader."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gitsage.context.ctx_reader import CTXReader, CTXContent
from gitsage.context.memory import MemoryManager, SUMMARIZE_EVERY
from gitsage.skills.loader import SkillLoader, Skill


# ---------------------------------------------------------------------------
# CTXReader tests
# ---------------------------------------------------------------------------

class TestCTXReaderEmpty:
    def test_ctx_reader_empty_returns_is_empty(self, tmp_path):
        """When no CTX.md exists in the tree, read() returns the empty sentinel."""
        reader = CTXReader(start_path=tmp_path)
        # Patch find_ctx_file to guarantee None
        with patch.object(reader, "find_ctx_file", return_value=None):
            result = reader.read()
        assert result.is_empty is True
        assert result.raw == ""
        assert result.always_rules == []
        assert result.never_rules == []


class TestCTXReaderParsesCommitRules:
    def test_ctx_reader_parses_commit_rules(self, tmp_path):
        ctx_file = tmp_path / "CTX.md"
        ctx_file.write_text(
            "# Project\n\n"
            "## Commit 规范\n"
            "格式：feat(<模块>): <描述>\n\n"
            "## Other Section\n"
            "some content\n",
            encoding="utf-8",
        )
        reader = CTXReader(start_path=tmp_path)
        result = reader.read()
        assert result.is_empty is False
        assert "feat" in result.commit_rules
        assert "模块" in result.commit_rules

    def test_ctx_reader_parses_english_commit_rules(self, tmp_path):
        ctx_file = tmp_path / "CTX.md"
        ctx_file.write_text(
            "## Commit Rules\n"
            "Use conventional commits: type(scope): description\n\n"
            "## Other\n"
            "stuff\n",
            encoding="utf-8",
        )
        reader = CTXReader(start_path=tmp_path)
        result = reader.read()
        assert "conventional" in result.commit_rules


class TestCTXReaderDetectsLanguage:
    def test_ctx_reader_detects_chinese_language(self, tmp_path):
        ctx_file = tmp_path / "CTX.md"
        # High ratio of CJK characters
        ctx_file.write_text(
            "# 项目文档\n\n"
            "## 项目背景\n"
            "这是一个测试项目，用于验证中文语言检测功能。"
            "系统需要正确识别中文内容并返回正确的语言标识。\n\n"
            "## Commit 规范\n"
            "提交信息格式：feat(模块): 描述内容\n",
            encoding="utf-8",
        )
        reader = CTXReader(start_path=tmp_path)
        result = reader.read()
        assert result.language == "zh"

    def test_ctx_reader_detects_english_language(self, tmp_path):
        ctx_file = tmp_path / "CTX.md"
        ctx_file.write_text(
            "# Project Documentation\n\n"
            "## Project Background\n"
            "This is a test project for verifying English language detection.\n\n"
            "## Commit Rules\n"
            "Use conventional commits format.\n",
            encoding="utf-8",
        )
        reader = CTXReader(start_path=tmp_path)
        result = reader.read()
        assert result.language == "en"


class TestCTXReaderParsesAlwaysNeverRules:
    def test_ctx_reader_parses_always_never_rules(self, tmp_path):
        ctx_file = tmp_path / "CTX.md"
        ctx_file.write_text(
            "# CTX\n\n"
            "## Rules\n\n"
            "always:\n"
            "  - inject ticket\n"
            "  - add scope\n\n"
            "never:\n"
            "  - no file paths\n"
            "  - no debug logs\n",
            encoding="utf-8",
        )
        reader = CTXReader(start_path=tmp_path)
        result = reader.read()
        assert "inject ticket" in result.always_rules
        assert "add scope" in result.always_rules
        assert "no file paths" in result.never_rules
        assert "no debug logs" in result.never_rules

    def test_ctx_reader_empty_rules_when_no_section(self, tmp_path):
        ctx_file = tmp_path / "CTX.md"
        ctx_file.write_text("# CTX\n\nJust some text, no rules.\n", encoding="utf-8")
        reader = CTXReader(start_path=tmp_path)
        result = reader.read()
        assert result.always_rules == []
        assert result.never_rules == []


# ---------------------------------------------------------------------------
# MemoryManager tests
# ---------------------------------------------------------------------------

class TestMemoryManagerAppendObservation:
    def test_memory_manager_append_observation(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        mgr.append_observation("commit", "added retry mechanism")
        content = mgr.read()
        assert "added retry mechanism" in content
        assert "commit" in content

    def test_memory_manager_append_multiple_observations(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        mgr.append_observation("commit", "first observation")
        mgr.append_observation("standup", "second observation")
        content = mgr.read()
        assert "first observation" in content
        assert "second observation" in content


class TestMemoryManagerCountObservations:
    def test_memory_manager_count_observations(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        for i in range(5):
            mgr.append_observation("commit", f"observation {i}")
        # should_summarize returns False when count < SUMMARIZE_EVERY
        assert not mgr.should_summarize()

    def test_memory_manager_get_raw_observations(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        mgr.append_observation("commit", "obs one")
        mgr.append_observation("standup", "obs two")
        obs = mgr.get_raw_observations()
        assert len(obs) == 2


class TestMemoryManagerShouldSummarize:
    def test_memory_manager_should_summarize(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        for i in range(SUMMARIZE_EVERY):
            mgr.append_observation("commit", f"observation number {i}")
        assert mgr.should_summarize() is True

    def test_memory_manager_should_not_summarize_below_threshold(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        for i in range(SUMMARIZE_EVERY - 1):
            mgr.append_observation("commit", f"observation {i}")
        assert mgr.should_summarize() is False


class TestMemoryManagerReadEmpty:
    def test_memory_manager_read_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("nonexistent/repo")
        result = mgr.read()
        assert result == ""

    def test_memory_manager_clear(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        mgr.append_observation("commit", "something")
        mgr.clear()
        assert mgr.read() == ""


# ---------------------------------------------------------------------------
# MemoryManager.record_commit and update_memory_async tests
# ---------------------------------------------------------------------------

class TestMemoryManagerRecordCommit:
    def test_record_commit_appends_observation(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        mgr.record_commit(message="feat: add thing", category="feat", branch="main")
        content = mgr.read()
        assert "feat: add thing" in content
        assert "commit" in content

    def test_record_commit_stores_category_and_branch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("test/repo")
        mgr.record_commit(message="fix: bug", category="fix", branch="feature/xyz")
        obs = mgr.get_raw_observations()
        assert len(obs) == 1
        assert "fix: bug" in obs[0]
        assert "fix" in obs[0]
        assert "feature/xyz" in obs[0]

    def test_record_commit_triggers_summarise_when_threshold_reached(
        self, tmp_path, monkeypatch
    ):
        from unittest.mock import MagicMock
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        monkeypatch.setattr("gitsage.context.memory.SUMMARIZE_EVERY", 3)
        mgr = MemoryManager("test/repo")

        mock_llm = MagicMock()
        mock_llm.complete.return_value = MagicMock(content="Summary text")

        for i in range(3):
            mgr.record_commit(f"feat: change {i}", llm_client=mock_llm)

        mock_llm.complete.assert_called_once()

    def test_record_commit_no_llm_skips_summarise(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        monkeypatch.setattr("gitsage.context.memory.SUMMARIZE_EVERY", 1)
        mgr = MemoryManager("test/repo")
        # Should not raise even though threshold is 1 and no llm_client
        mgr.record_commit("feat: something", llm_client=None)


class TestUpdateMemoryAsync:
    def test_async_update_does_not_raise(self, tmp_path, monkeypatch):
        """update_memory_async must never raise — it's fire-and-forget."""
        from gitsage.context.memory import update_memory_async
        # Should not raise even with a bad repo name or no LLM
        update_memory_async("owner/repo", "feat: async test", "feat", "main", None)
        # Success = no exception raised

    def test_async_update_writes_to_memory_synchronously_via_record_commit(
        self, tmp_path, monkeypatch
    ):
        """Verify the underlying record_commit works (thread timing aside)."""
        monkeypatch.setattr("gitsage.context.memory.MEMORY_DIR", tmp_path)
        mgr = MemoryManager("owner/repo")
        mgr.record_commit("feat: direct test", "feat", "main", None)
        assert "feat: direct test" in mgr.read()


# ---------------------------------------------------------------------------
# SkillLoader tests
# ---------------------------------------------------------------------------

class TestSkillLoaderLoadsProjectSkill:
    def test_skill_loader_loads_project_skill(self, tmp_path):
        skill_dir = tmp_path / ".gitsage" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "trigger: auto\n"
            "---\n"
            "# My Skill\n\n"
            "This is the skill body.\n",
            encoding="utf-8",
        )
        loader = SkillLoader(repo_path=tmp_path)
        skill = loader.load("my-skill")
        assert skill is not None
        assert skill.name == "my-skill"
        assert skill.description == "A test skill"

    def test_skill_loader_loads_skill_body(self, tmp_path):
        skill_dir = tmp_path / ".gitsage" / "skills" / "body-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: body-skill\n"
            "description: Has body\n"
            "---\n"
            "# Body Content\n"
            "Some instructions here.\n",
            encoding="utf-8",
        )
        loader = SkillLoader(repo_path=tmp_path)
        skill = loader.load("body-skill")
        assert skill is not None
        assert "Body Content" in skill.content or "instructions" in skill.content


class TestSkillLoaderParsesFrontmatter:
    def test_skill_loader_parses_frontmatter(self, tmp_path):
        skill_dir = tmp_path / ".gitsage" / "skills" / "fm-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: fm-skill\n"
            "description: Frontmatter skill\n"
            "trigger: manual\n"
            "---\n"
            "Skill body here.\n",
            encoding="utf-8",
        )
        loader = SkillLoader(repo_path=tmp_path)
        skill = loader.load("fm-skill")
        assert skill is not None
        assert skill.trigger == "manual"
        assert skill.description == "Frontmatter skill"
        assert "Skill body" in skill.content

    def test_skill_loader_uses_dir_name_when_no_name_in_frontmatter(self, tmp_path):
        skill_dir = tmp_path / ".gitsage" / "skills" / "dir-name-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "No frontmatter here, just plain content.\n",
            encoding="utf-8",
        )
        loader = SkillLoader(repo_path=tmp_path)
        skill = loader.load("dir-name-skill")
        assert skill is not None
        assert skill.name == "dir-name-skill"


class TestSkillLoaderMissingReturnsNone:
    def test_skill_loader_missing_returns_none(self, tmp_path):
        loader = SkillLoader(repo_path=tmp_path)
        result = loader.load("nonexistent-skill")
        assert result is None

    def test_skill_loader_load_all_empty_dirs(self, tmp_path):
        loader = SkillLoader(repo_path=tmp_path)
        skills = loader.load_all()
        assert isinstance(skills, list)
        # May or may not have global skills — just check it's a list


# ---------------------------------------------------------------------------
# skill add / show / edit CLI command tests
# ---------------------------------------------------------------------------

class TestSkillAddFileCreation:
    """Test that skill add creates a correctly formed SKILL.md."""

    def _invoke_skill_add(self, tmp_path, name: str, scope: str = "project", monkeypatch=None):
        """Helper: run skill_add with mocked prompts."""
        from typer.testing import CliRunner
        from gitsage.cli import app
        from gitsage.skills.loader import PROJECT_SKILLS_DIR_NAME

        runner = CliRunner()

        # Prompt.ask calls:  name (if not given), description, trigger choice
        with patch("gitsage.cli.Prompt.ask", side_effect=["A test skill desc", "1"]), \
             patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["skill", "add", name, "--scope", scope])

        return result

    def test_skill_add_creates_skill_md(self, tmp_path, monkeypatch):
        from gitsage.skills.loader import PROJECT_SKILLS_DIR_NAME
        from typer.testing import CliRunner
        from gitsage.cli import app

        runner = CliRunner()
        with patch("gitsage.cli.Prompt.ask", side_effect=["A test skill desc", "1"]), \
             patch("pathlib.Path.cwd", return_value=tmp_path):
            runner.invoke(app, ["skill", "add", "my-test-skill", "--scope", "project"])

        skill_file = tmp_path / PROJECT_SKILLS_DIR_NAME / "my-test-skill" / "SKILL.md"
        assert skill_file.exists(), f"Expected {skill_file} to exist"

    def test_skill_add_frontmatter_is_valid(self, tmp_path):
        from gitsage.skills.loader import PROJECT_SKILLS_DIR_NAME
        from typer.testing import CliRunner
        from gitsage.cli import app

        runner = CliRunner()
        with patch("gitsage.cli.Prompt.ask", side_effect=["My desc", "1"]), \
             patch("pathlib.Path.cwd", return_value=tmp_path):
            runner.invoke(app, ["skill", "add", "alpha-skill", "--scope", "project"])

        skill_file = tmp_path / PROJECT_SKILLS_DIR_NAME / "alpha-skill" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        assert "name: alpha-skill" in content
        assert "description: My desc" in content
        assert "trigger: auto" in content

    def test_skill_add_created_skill_is_loadable(self, tmp_path):
        """SkillLoader should be able to load the file created by skill add."""
        from gitsage.skills.loader import PROJECT_SKILLS_DIR_NAME
        from typer.testing import CliRunner
        from gitsage.cli import app

        runner = CliRunner()
        with patch("gitsage.cli.Prompt.ask", side_effect=["Loadable desc", "1"]), \
             patch("pathlib.Path.cwd", return_value=tmp_path):
            runner.invoke(app, ["skill", "add", "loadable-skill", "--scope", "project"])

        loader = SkillLoader(repo_path=tmp_path)
        skill = loader.load("loadable-skill")
        assert skill is not None
        assert skill.name == "loadable-skill"
        assert skill.description == "Loadable desc"
        assert skill.trigger == "auto"

    def test_skill_add_duplicate_returns_nonzero(self, tmp_path):
        """Adding a skill that already exists should exit with code 1."""
        from gitsage.skills.loader import PROJECT_SKILLS_DIR_NAME
        from typer.testing import CliRunner
        from gitsage.cli import app

        # Create the skill first
        skill_dir = tmp_path / PROJECT_SKILLS_DIR_NAME / "dup-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: dup-skill\n---\n", encoding="utf-8")

        runner = CliRunner()
        with patch("gitsage.cli.Prompt.ask", side_effect=["desc", "1"]), \
             patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["skill", "add", "dup-skill", "--scope", "project"])

        assert result.exit_code == 1

    def test_skill_add_invalid_name_returns_nonzero(self, tmp_path):
        """Names with uppercase or special chars should exit with code 1."""
        from typer.testing import CliRunner
        from gitsage.cli import app

        runner = CliRunner()
        # "INVALID_NAME" contains uppercase — regex rejects it
        with patch("gitsage.cli.Prompt.ask", side_effect=["desc", "1"]), \
             patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["skill", "add", "INVALID_NAME", "--scope", "project"])

        assert result.exit_code == 1


class TestSkillShowCommand:
    def test_skill_show_existing_skill(self, tmp_path):
        from typer.testing import CliRunner
        from gitsage.cli import app
        from gitsage.skills.loader import PROJECT_SKILLS_DIR_NAME

        skill_dir = tmp_path / PROJECT_SKILLS_DIR_NAME / "show-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: show-skill\ndescription: A visible skill\ntrigger: manual\n---\n"
            "# Show Skill\nInstructions here.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["skill", "show", "show-skill"])

        assert result.exit_code == 0
        assert "show-skill" in result.output
        assert "manual" in result.output

    def test_skill_show_missing_skill_returns_nonzero(self, tmp_path):
        from typer.testing import CliRunner
        from gitsage.cli import app

        runner = CliRunner()
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["skill", "show", "ghost-skill"])

        assert result.exit_code == 1
