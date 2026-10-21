from __future__ import annotations

import pytest

from quicktools.plugins.calculator.engine import (
    MAX_EXPRESSION_LENGTH,
    ExpressionError,
    convert_bases,
    evaluate,
    evaluate_live,
    filter_input,
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


def test_result_grouping() -> None:
    assert format_result(1000, 10, 3) == "1,000"
    assert format_result(-1234567, 10, 3) == "-1,234,567"
    assert format_result(1234567.89, 10, 3) == "1,234,567.89"
    assert format_result(1000, 10, 4) == "1000"
    assert format_result(10000, 10, 4) == "1,0000"
    assert format_result(1000, 10, 0) == "1000"
    assert format_result(255, 16, 3) == "0xFF"
    assert format_result(1e20, 10, 3) == "100,000,000,000,000,000,000"
    assert format_result(1e-7, 10, 3) == "1e-07"


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


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1", 1),
        ("1+", 1),
        ("1-", 1),
        ("1*", 1),
        ("1/", 1),
        ("1%", 0),
        ("1+2*", 3),
        ("1+2+", 3),
        ("(1+2)*", 3),
        ("8/2*", 4),
        (" 1 + ", 1),
    ],
)
def test_live_evaluation_completes_dangling_operand(
    expression: str, expected: int | float
) -> None:
    assert evaluate_live(expression) == expected


@pytest.mark.parametrize(
    "expression",
    ["1^", "1**", "1+(1+", "1+(1+2", "1/0", "-", "1*-", ""],
)
def test_live_evaluation_rejects_uncalculable_input(expression: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate_live(expression)


def test_live_evaluation_uses_active_base() -> None:
    assert evaluate_live("10+", 16) == 16
    assert evaluate_live("FF*", 16) == 255


@pytest.mark.parametrize(
    ("text", "base", "expected"),
    [
        ("12+34", 10, "12+34"),
        ("12a+34", 10, "12+34"),
        ("0xFF+1", 10, "0xFF+1"),
        ("1.25", 10, "1.25"),
        ("１＋２", 10, "1+2"),
        ("11+11", 16, "11+11"),
        ("G+1", 16, "+1"),
        ("FF+1", 16, "FF+1"),
        ("1.5G", 16, "15"),
        ("178+1", 8, "17+1"),
        ("102", 2, "10"),
        ("0xFF", 2, "0xFF"),
    ],
)
def test_input_filter_matches_active_base(
    text: str, base: int, expected: str
) -> None:
    assert filter_input(text, base) == expected
