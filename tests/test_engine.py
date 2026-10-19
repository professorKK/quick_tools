from __future__ import annotations

import pytest

from quicktools.plugins.calculator.engine import (
    MAX_EXPRESSION_LENGTH,
    ExpressionError,
    convert_bases,
    evaluate,
    format_int,
    format_result,
    normalize_text,
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1+1", 2),
        ("2+3*4", 14),
        ("(2+3)*4", 20),
        ("2^10", 1024),
        ("2**10", 1024),
        ("2^3^2", 512),
        ("-2^2", -4),
        ("2^-2", 0.25),
        ("7//2", 3),
        ("7%4", 3),
        ("10/4", 2.5),
        (".5+1", 1.5),
        ("  3 + 4  ", 7),
    ],
)
def test_arithmetic(expression: str, expected) -> None:
    assert evaluate(expression) == expected


def test_fullwidth_normalization() -> None:
    assert normalize_text("（１＋２）×３－４÷２＾２") == "(1+2)*3-4/2^2"
    assert evaluate("（１＋２）×３－４÷２＾２") == 8


def test_explicit_bases_any_mode() -> None:
    assert evaluate("0xFF + 1") == 256
    assert evaluate("0b1010 + 0o7") == 17
    assert evaluate("0X10") == 16


def test_active_base_for_bare_numbers() -> None:
    assert evaluate("FF+1", 16) == 256
    assert evaluate("10+1", 16) == 17
    assert evaluate("11+1", 8) == 10
    assert evaluate("101+1", 2) == 6


def test_base_conversions() -> None:
    assert convert_bases(255) == {
        10: "255",
        16: "0xFF",
        8: "0o377",
        2: "0b1111 1111",
    }
    assert convert_bases(-10)[16] == "-0xA"
    assert convert_bases(4.0)[2] == "0b100"
    assert convert_bases(1.5) == {10: "1.5", 16: None, 8: None, 2: None}


def test_formatting() -> None:
    assert format_int(0, 2) == "0b0"
    assert format_int(32, 2) == "0b10 0000"
    assert format_result(255, 16) == "0xFF"
    assert format_result(4.0, 10) == "4"
    assert format_result(0.5, 10) == "0.5"


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "1/0",
        "1//0",
        "1%0",
        "(1+2",
        "1+2)",
        "1..2",
        "1.2.3",
        "2^50001",
        "2^999999999",
        "0x",
        "0b102",
        "FF",
    ],
)
def test_errors(expression: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate(expression)


def test_invalid_digit_in_active_base() -> None:
    with pytest.raises(ExpressionError):
        evaluate("8", 8)
    with pytest.raises(ExpressionError):
        evaluate("2", 2)
    with pytest.raises(ExpressionError):
        evaluate("G", 16)


def test_expression_length_guard() -> None:
    with pytest.raises(ExpressionError):
        evaluate("1+" * (MAX_EXPRESSION_LENGTH // 2 + 1) + "1")


def test_deep_parentheses_guard() -> None:
    expression = "(" * 120 + "1" + ")" * 120
    with pytest.raises(ExpressionError):
        evaluate(expression)


def test_division_is_true_division() -> None:
    value = evaluate("1/3")
    assert isinstance(value, float)
    assert value == pytest.approx(1 / 3)
