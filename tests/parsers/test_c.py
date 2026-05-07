"""C parser: lightweight top-level function extraction."""

from __future__ import annotations


def test_c_parser_extracts_top_level_functions(parse_c):
    parsed = parse_c(
        """
        static int helper(int value)
        {
            return value + 1;
        }

        int exported_name(struct foo *foo)
        {
            return helper(foo->value);
        }
        """
    )

    assert [s.name for s in parsed.symbols] == ["helper", "exported_name"]
    assert parsed.symbols[0].kind == "function"


def test_c_parser_skips_prototypes_and_calls(parse_c):
    parsed = parse_c(
        """
        int prototype_only(int arg);

        int real_function(void)
        {
            if (prototype_only(1)) {
                return 1;
            }
            return 0;
        }
        """
    )

    assert [s.name for s in parsed.symbols] == ["real_function"]


def test_c_parser_extracts_kernel_syscall_macro(parse_c):
    parsed = parse_c(
        """
        SYSCALL_DEFINE6(io_uring_enter, unsigned int, fd, u32, to_submit,
                        u32, min_complete, u32, flags,
                        const void __user *, argp, size_t, argsz)
        {
            return 0;
        }
        """
    )

    assert parsed.symbols[0].name == "__io_uring_enter"
    assert parsed.symbols[0].qualname == "__io_uring_enter"
