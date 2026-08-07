"""Tests for _handlers.py's _count_error_signals / _SOURCE_CODE_LINE_RE.

Regression coverage for a live false-positive: reading source files via
sed/rg/cat whose content merely contains "except Exception:" or similar
exception-handling syntax was being counted as real error output and
triggering the "Error detected in command output" PostToolUse context.
"""

from __future__ import annotations


def test_source_code_except_blocks_not_counted_as_errors():
    from _handlers import _count_error_signals

    text = "\n".join(
        [
            "def foo():",
            "    try:",
            "        do_thing()",
            "    except Exception:",
            "        logger.warning('failed')",
            "",
            "def bar():",
            "    try:",
            "        do_other_thing()",
            "    except Exception:",
            "        pass",
        ]
    )
    assert _count_error_signals(text) == 0


def test_class_exception_declarations_not_counted():
    from _handlers import _count_error_signals

    text = "\n".join(
        [
            "class ValidationException:",
            "    pass",
            "",
            "class NotFoundException:",
            "    pass",
        ]
    )
    assert _count_error_signals(text) == 0


def test_real_error_output_still_counted():
    from _handlers import _count_error_signals

    text = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "app.py", line 10, in <module>',
            "    raise ValueError('bad input')",
            "ValueError: bad input",
            "Error: process exited with code 1",
        ]
    )
    assert _count_error_signals(text) >= 2


def test_grep_context_dump_of_except_blocks_not_counted():
    """The exact live failure mode: `rg -C 8` context output repeating
    except-clause lines from source, not an actual command failure."""
    from _handlers import _count_error_signals

    text = "\n".join(
        [
            "services/foo.py-150-    try:",
            "services/foo.py-151-        fetch()",
            "services/foo.py:152:    except Exception:",
            "services/foo.py-153-        return None",
            "--",
            "services/bar.py-200-    try:",
            "services/bar.py-201-        fetch()",
            "services/bar.py:202:    except Exception:",
            "services/bar.py-203-        return None",
        ]
    )
    assert _count_error_signals(text) == 0
