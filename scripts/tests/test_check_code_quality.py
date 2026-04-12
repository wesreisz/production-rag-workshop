import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_code_quality import check_ast, check_comments, check_file

CASES_COMMENTS = [
    ("# TODO: fix this later\n", [(1, "TODO found in comment")]),
    ("# FIXME: broken\n", [(1, "FIXME found in comment")]),
    ("# todo lowercase\n", [(1, "TODO found in comment")]),
    ("# fixme lowercase\n", [(1, "FIXME found in comment")]),
    ("# TODO and FIXME on same line\n", [
        (1, "TODO found in comment"),
        (1, "FIXME found in comment"),
    ]),
    ("# Nothing wrong here\n", []),
    ("x = 1  # clean trailing comment\n", []),
    ("# TODOIST is not a match\nx = 1\n", []),
    ("x = 1\n# Line 2 FIXME\n", [(2, "FIXME found in comment")]),
]

CASES_AST = [
    ("return NotImplemented\n", [(1, "NotImplemented reference found")]),
    ("raise NotImplementedError\n", [(1, "raise NotImplementedError found")]),
    ("raise NotImplementedError('msg')\n", [(1, "raise NotImplementedError found")]),
    ("raise builtins.NotImplementedError()\n", [(1, "raise NotImplementedError found")]),
    ("x = 1\n", []),
    ("raise ValueError('ok')\n", []),
]


class TestCheckComments:
    @pytest.mark.parametrize("source,expected", CASES_COMMENTS, ids=[
        "todo_uppercase",
        "fixme_uppercase",
        "todo_lowercase",
        "fixme_lowercase",
        "both_on_same_line",
        "clean_comment",
        "clean_trailing",
        "todoist_no_boundary",
        "fixme_on_line_2",
    ])
    def test_comment_detection(self, tmp_path, source, expected):
        # Arrange
        f = tmp_path / "sample.py"
        f.write_text(source)

        # Act
        result = check_comments(str(f))

        # Assert
        assert result == expected


class TestCheckAst:
    @pytest.mark.parametrize("source,expected", CASES_AST, ids=[
        "return_not_implemented",
        "raise_not_implemented_error_bare",
        "raise_not_implemented_error_call",
        "raise_qualified_not_implemented_error",
        "clean_code",
        "raise_value_error",
    ])
    def test_ast_detection(self, tmp_path, source, expected):
        # Arrange
        f = tmp_path / "sample.py"
        f.write_text(source)

        # Act
        result = check_ast(str(f))

        # Assert
        assert result == expected


class TestCheckFile:
    def test_combines_comment_and_ast_violations(self, tmp_path):
        # Arrange
        source = "# TODO: placeholder\nraise NotImplementedError\n"
        f = tmp_path / "sample.py"
        f.write_text(source)
        path = str(f)

        # Act
        result = check_file(path)

        # Assert
        assert len(result) == 2
        assert result[0] == (path, 1, "TODO found in comment")
        assert result[1] == (path, 2, "raise NotImplementedError found")

    def test_clean_file_returns_empty(self, tmp_path):
        # Arrange
        f = tmp_path / "sample.py"
        f.write_text("x = 1\ny = 2\n")

        # Act
        result = check_file(str(f))

        # Assert
        assert result == []

    def test_syntax_error_file_warns(self, tmp_path, capsys):
        # Arrange
        f = tmp_path / "bad.py"
        f.write_text("def (:\n")

        # Act
        result = check_ast(str(f))

        # Assert
        assert result == []
        captured = capsys.readouterr()
        assert "syntax error" in captured.err
