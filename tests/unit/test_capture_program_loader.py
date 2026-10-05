from __future__ import annotations

import pytest

from caelum.capture_runtime import ProgramLoadError, builtin_program, load_program
from caelum.capture_runtime.program import builtin_names, source_sha256

GOOD = '''
PROGRAM = {"description": "test", "timeout_s": 5}

async def capture(ctx):
    return None
'''


def test_loads_program_with_meta_and_hash():
    program = load_program("good.py", GOOD)
    assert program.meta == {"description": "test", "timeout_s": 5}
    assert program.sha256 == source_sha256(GOOD)
    assert program.origin == "user"
    assert program.identity["name"] == "good.py"


@pytest.mark.parametrize(
    "source,message",
    [
        ("def capture(ctx):\n    pass\n", "async def capture"),
        ("async def capture(ctx, other):\n    pass\n", "exactly one argument"),
        ("x = 1\n", "async def capture"),
        ("async def capture(ctx)\n", "syntax error at line 1"),
        ("raise RuntimeError('boom')\n", "failed to load"),
        ("PROGRAM = {'a': len('x')}\nasync def capture(ctx):\n    pass\n", "literal"),
        ("PROGRAM = [1]\nasync def capture(ctx):\n    pass\n", "must be a dict"),
    ],
)
def test_rejects_bad_programs(source, message):
    with pytest.raises(ProgramLoadError, match=message):
        load_program("bad.py", source)


def test_tracebacks_show_program_lines():
    import traceback

    program = load_program("tb.py", "async def capture(ctx):\n    raise ValueError('here')\n")
    coro = program.capture(None)
    with pytest.raises(ValueError) as info:
        coro.send(None)
    text = "".join(traceback.format_exception(info.value))
    assert "<capture-program tb.py>" in text
    assert "raise ValueError('here')" in text


def test_builtin_default_is_available():
    assert "default.py" in builtin_names()
    program = builtin_program()
    assert program.origin == "builtin"
    assert program.meta["kind"] == "single"
