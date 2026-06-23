"""Tests for gitsage agent models and LLM client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from gitsage.agent.models import CommitCandidate, CommitOutput, StandupOutput
from gitsage.agent.llm import (
    OpenAICompatibleClient,
    LLMError,
    LLMValidationError,
    _parse_json_response,
)
from gitsage.config import LLMConfig


# ---------------------------------------------------------------------------
# CommitOutput / CommitCandidate model tests
# ---------------------------------------------------------------------------

class TestCommitOutputRequiresAtLeastOneCandidate:
    def test_commit_output_requires_at_least_one_candidate(self):
        with pytest.raises(ValidationError):
            CommitOutput(candidates=[], warning=None)

    def test_commit_output_with_one_candidate_is_valid(self):
        output = CommitOutput(
            candidates=[
                CommitCandidate(
                    message="feat: add feature",
                    confidence="high",
                    reason="Clear intent",
                )
            ],
            warning=None,
        )
        assert len(output.candidates) == 1


class TestCommitOutputMax3Candidates:
    def test_commit_output_max_3_candidates(self):
        """4 candidates should raise a ValidationError."""
        with pytest.raises(ValidationError):
            CommitOutput(
                candidates=[
                    CommitCandidate(message=f"feat: option {i}", confidence="low", reason="r")
                    for i in range(4)
                ],
                warning=None,
            )

    def test_commit_output_exactly_3_candidates_is_valid(self):
        output = CommitOutput(
            candidates=[
                CommitCandidate(message=f"feat: option {i}", confidence="high", reason="r")
                for i in range(3)
            ],
            warning=None,
        )
        assert len(output.candidates) == 3


class TestCommitCandidateConfidenceValues:
    def test_commit_candidate_confidence_high(self):
        c = CommitCandidate(message="feat: x", confidence="high", reason="r")
        assert c.confidence == "high"

    def test_commit_candidate_confidence_medium(self):
        c = CommitCandidate(message="feat: x", confidence="medium", reason="r")
        assert c.confidence == "medium"

    def test_commit_candidate_confidence_low(self):
        c = CommitCandidate(message="feat: x", confidence="low", reason="r")
        assert c.confidence == "low"

    def test_commit_candidate_invalid_confidence_raises(self):
        with pytest.raises(ValidationError):
            CommitCandidate(message="feat: x", confidence="very-high", reason="r")

    def test_commit_candidate_invalid_confidence_none_raises(self):
        with pytest.raises(ValidationError):
            CommitCandidate(message="feat: x", confidence="uncertain", reason="r")


# ---------------------------------------------------------------------------
# _parse_json_response helper tests
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_parse_valid_json(self):
        payload = json.dumps({
            "candidates": [
                {"message": "feat: add x", "confidence": "high", "reason": "clear"}
            ],
            "warning": None,
        })
        result = _parse_json_response(payload, CommitOutput)
        assert result.candidates[0].message == "feat: add x"

    def test_strips_markdown_fences(self):
        payload = (
            "```json\n"
            + json.dumps({
                "candidates": [
                    {"message": "feat: stripped", "confidence": "medium", "reason": "ok"}
                ],
                "warning": None,
            })
            + "\n```"
        )
        result = _parse_json_response(payload, CommitOutput)
        assert result.candidates[0].message == "feat: stripped"

    def test_strips_plain_code_fence(self):
        payload = (
            "```\n"
            + json.dumps({
                "candidates": [
                    {"message": "fix: plain fence", "confidence": "low", "reason": "test"}
                ],
                "warning": None,
            })
            + "\n```"
        )
        result = _parse_json_response(payload, CommitOutput)
        assert result.candidates[0].message == "fix: plain fence"

    def test_raises_on_bad_json(self):
        with pytest.raises(LLMValidationError, match="not valid JSON"):
            _parse_json_response("this is not json at all!!!", CommitOutput)

    def test_raises_on_schema_mismatch(self):
        # Valid JSON but wrong schema (missing required 'candidates')
        payload = json.dumps({"wrong_field": "value"})
        with pytest.raises(LLMValidationError):
            _parse_json_response(payload, CommitOutput)

    def test_raises_on_empty_candidates_schema(self):
        payload = json.dumps({"candidates": [], "warning": None})
        with pytest.raises(LLMValidationError):
            _parse_json_response(payload, CommitOutput)


# ---------------------------------------------------------------------------
# OpenAICompatibleClient tests (mocked)
# ---------------------------------------------------------------------------

def _make_openai_response(content: str):
    """Build a minimal mock object matching openai.ChatCompletion response shape."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


VALID_COMMIT_JSON = json.dumps({
    "candidates": [
        {"message": "feat(pay): add retry", "confidence": "high", "reason": "clear diff"}
    ],
    "warning": None,
})


class TestOpenAICompatibleClientParsesJson:
    def test_openai_compatible_client_parses_json(self):
        cfg = LLMConfig(provider="deepseek", api_key="test-key")
        mock_response = _make_openai_response(VALID_COMMIT_JSON)

        with patch("openai.OpenAI") as MockOpenAI:
            mock_instance = MagicMock()
            MockOpenAI.return_value = mock_instance
            mock_instance.chat.completions.create.return_value = mock_response

            client = OpenAICompatibleClient(cfg)
            client._client = mock_instance

            result = client.complete(
                system="You are a commit assistant.",
                user="Generate a commit message.",
                output_model=CommitOutput,
            )

        assert isinstance(result, CommitOutput)
        assert result.candidates[0].message == "feat(pay): add retry"
        assert result.candidates[0].confidence == "high"


class TestOpenAICompatibleClientStripsMarkdownFences:
    def test_openai_compatible_client_strips_markdown_fences(self):
        cfg = LLMConfig(provider="deepseek", api_key="test-key")
        fenced_response = f"```json\n{VALID_COMMIT_JSON}\n```"
        mock_response = _make_openai_response(fenced_response)

        with patch("openai.OpenAI") as MockOpenAI:
            mock_instance = MagicMock()
            MockOpenAI.return_value = mock_instance
            mock_instance.chat.completions.create.return_value = mock_response

            client = OpenAICompatibleClient(cfg)
            client._client = mock_instance

            result = client.complete(
                system="system",
                user="user",
                output_model=CommitOutput,
            )

        assert isinstance(result, CommitOutput)
        assert result.candidates[0].message == "feat(pay): add retry"


class TestOpenAICompatibleClientRaisesOnBadJson:
    def test_openai_compatible_client_raises_on_bad_json(self):
        cfg = LLMConfig(provider="deepseek", api_key="test-key")
        mock_response = _make_openai_response("This is garbage, not JSON!!!")

        with patch("openai.OpenAI") as MockOpenAI:
            mock_instance = MagicMock()
            MockOpenAI.return_value = mock_instance
            mock_instance.chat.completions.create.return_value = mock_response

            client = OpenAICompatibleClient(cfg)
            client._client = mock_instance

            with pytest.raises(LLMValidationError):
                client.complete(
                    system="system",
                    user="user",
                    output_model=CommitOutput,
                )


class TestOpenAICompatibleClientRaisesOnSchemaMismatch:
    def test_openai_compatible_client_raises_on_schema_mismatch(self):
        cfg = LLMConfig(provider="deepseek", api_key="test-key")
        # Valid JSON but wrong schema
        wrong_schema = json.dumps({"title": "PR title", "description": "some PR"})
        mock_response = _make_openai_response(wrong_schema)

        with patch("openai.OpenAI") as MockOpenAI:
            mock_instance = MagicMock()
            MockOpenAI.return_value = mock_instance
            mock_instance.chat.completions.create.return_value = mock_response

            client = OpenAICompatibleClient(cfg)
            client._client = mock_instance

            with pytest.raises(LLMValidationError):
                client.complete(
                    system="system",
                    user="user",
                    output_model=CommitOutput,
                )


# ---------------------------------------------------------------------------
# StandupOutput model tests
# ---------------------------------------------------------------------------

class TestStandupOutputModel:
    def test_standup_output_basic(self):
        out = StandupOutput(content="Worked on auth module.", items=["auth", "tests"])
        assert out.content == "Worked on auth module."
        assert "auth" in out.items

    def test_standup_output_empty_items_default(self):
        out = StandupOutput(content="Some standup content.")
        assert out.items == []
