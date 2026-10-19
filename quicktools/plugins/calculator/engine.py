"""Safe expression engine for the calculator.

This module intentionally does not use ``eval``. It implements a small
recursive-descent parser with exact integer arithmetic and a few resource
guards so a stray expression cannot freeze the UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


SUPPORTED_BASES = (10, 16, 8, 2)
BASE_LABELS = {10: "DEC", 16: "HEX", 8: "OCT", 2: "BIN"}
BASE_PREFIX = {16: "0x", 8: "0o", 2: "0b"}

MAX_EXPRESSION_LENGTH = 4096
MAX_PAREN_DEPTH = 100
MAX_EXPONENT = 50_000
MAX_RESULT_BITS = 100_000

_FULLWIDTH_MAP = str.maketrans(
    {
        "０": "0",
        "１": "1",
        "２": "2",
        "３": "3",
        "４": "4",
        "５": "5",
        "６": "6",
        "７": "7",
        "８": "8",
        "９": "9",
        "（": "(",
        "）": ")",
        "＋": "+",
        "－": "-",
        "＊": "*",
        "／": "/",
        "＾": "^",
        "％": "%",
        "．": ".",
        "。": ".",
        "×": "*",
        "÷": "/",
        "−": "-",  # U+2212 minus sign
        "–": "-",
        "—": "-",
        "　": " ",
    }
)

_DECIMAL_DIGITS = frozenset("0123456789")
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_DIGITS_BY_BASE = {
    2: frozenset("01"),
    8: frozenset("01234567"),
    10: _DECIMAL_DIGITS,
    16: _HEX_DIGITS,
}


class ExpressionError(ValueError):
    """A user-facing expression error."""


@dataclass(frozen=True)
class Token:
    kind: str  # NUM, OP, LPAREN, RPAREN, EOF
    value: Any
    pos: int


def normalize_text(text: str) -> str:
    """Normalize full-width/CJK symbols; every replacement is one character.

    Keeping replacements 1:1 means callers can preserve the caret index.
    """
    return text.translate(_FULLWIDTH_MAP)


def validate_base(base: int) -> int:
    if base not in _DIGITS_BY_BASE:
        raise ExpressionError(f"不支持的进制：{base}")
    return base


def _error(message: str, pos: int | None = None) -> ExpressionError:
    if pos is None:
        return ExpressionError(message)
    return ExpressionError(f"{message}（第 {pos + 1} 个字符）")


def _tokenize(text: str, base: int) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue

        if ch == "(":
            tokens.append(Token("LPAREN", ch, i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token("RPAREN", ch, i))
            i += 1
            continue

        two = text[i : i + 2]
        if two in ("**", "//"):
            tokens.append(Token("OP", two, i))
            i += 2
            continue
        if ch in "+-*/%^":
            tokens.append(Token("OP", ch, i))
            i += 1
            continue

        number, next_i = _read_number(text, i, base)
        if number is not None:
            tokens.append(Token("NUM", number, i))
            i = next_i
            continue

        raise _error(f"无法识别的字符 {ch!r}", i)

    tokens.append(Token("EOF", None, n))
    return tokens


def _read_number(text: str, start: int, base: int) -> tuple[int | float | None, int]:
    """Return (value, next_index) or (None, start) if this is not a number."""
    n = len(text)
    i = start
    ch = text[i]

    prefix_info = {
        "0x": (16, _HEX_DIGITS, "十六进制"),
        "0X": (16, _HEX_DIGITS, "十六进制"),
        "0b": (2, _DIGITS_BY_BASE[2], "二进制"),
        "0B": (2, _DIGITS_BY_BASE[2], "二进制"),
        "0o": (8, _DIGITS_BY_BASE[8], "八进制"),
        "0O": (8, _DIGITS_BY_BASE[8], "八进制"),
    }
    if text[i : i + 2] in prefix_info:
        number_base, valid_digits, label = prefix_info[text[i : i + 2]]
        j = i + 2
        while j < n and text[j] in valid_digits:
            j += 1
        if j == i + 2:
            raise _error(f"{label}前缀后缺少数字", i)
        if j < n and (text[j].isalnum() or text[j] in "._"):
            raise _error(f"{label}数字格式无效", j)
        return int(text[i + 2 : j], number_base), j

    if base == 10:
        if not (ch.isdigit() or ch == "."):
            return None, start
        j = i
        dot_count = 0
        while j < n and (text[j].isdigit() or text[j] == "."):
            if text[j] == ".":
                dot_count += 1
                if dot_count > 1:
                    raise _error("数字中只能有一个小数点", j)
            j += 1
        raw = text[i:j]
        if raw == ".":
            raise _error("小数点前后缺少数字", i)
        if j < n and text[j].isalnum():
            raise _error(f"十进制无法识别字符 {text[j]!r}", j)
        if dot_count:
            try:
                return float(raw), j
            except ValueError:
                raise _error("小数格式无效", i) from None
        return int(raw, 10), j

    # In a non-decimal mode bare tokens may start with a hex letter.
    if not ch.isalnum():
        return None, start
    j = i
    while j < n and text[j].isalnum():
        j += 1
    raw = text[i:j]
    valid = _DIGITS_BY_BASE[base]
    for offset, digit in enumerate(raw):
        if digit not in valid:
            hint = "（A-F 仅在 HEX 模式可用）" if base != 16 else ""
            raise _error(
                f"{BASE_LABELS[base]} 模式不允许数字 {digit!r}{hint}", i + offset
            )
    return int(raw, base), j


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def _advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def _match_op(self, *operators: str) -> str | None:
        token = self.current
        if token.kind == "OP" and token.value in operators:
            self._advance()
            return token.value
        return None

    def parse(self) -> int | float:
        value = self._expression()
        token = self.current
        if token.kind == "EOF":
            return self._check_result(value)
        if token.kind == "RPAREN":
            raise _error("括号不匹配：多余的 ')'", token.pos)
        raise _error("运算符之间缺少内容", token.pos)

    def _expression(self) -> int | float:
        value = self._term()
        while True:
            op = self._match_op("+", "-")
            if op is None:
                return value
            rhs = self._term()
            try:
                value = value + rhs if op == "+" else value - rhs
            except OverflowError:
                raise _error("结果超出可计算范围") from None
            self._check_result(value)

    def _term(self) -> int | float:
        value = self._unary()
        while True:
            op = self._match_op("*", "/", "//", "%")
            if op is None:
                return value
            rhs = self._unary()
            if op in ("/", "//", "%") and rhs == 0:
                raise _error("不能除以零")
            try:
                if op == "*":
                    value = value * rhs
                elif op == "/":
                    value = value / rhs
                elif op == "//":
                    value = value // rhs
                else:
                    value = value % rhs
            except ZeroDivisionError:
                raise _error("不能除以零") from None
            except OverflowError:
                raise _error("结果超出可计算范围") from None
            self._check_result(value)

    def _unary(self) -> int | float:
        op = self._match_op("+", "-")
        if op is None:
            return self._power()
        value = self._unary()
        return value if op == "+" else -value

    def _power(self) -> int | float:
        base = self._primary()
        op = self._match_op("^", "**")
        if op is None:
            return base
        exponent = self._unary()  # right associative
        if isinstance(exponent, (int, float)) and abs(exponent) > MAX_EXPONENT:
            raise _error(f"指数绝对值不能超过 {MAX_EXPONENT}")
        try:
            result = base**exponent
        except ZeroDivisionError:
            raise _error("零不能作为负指数") from None
        except OverflowError:
            raise _error("结果超出可计算范围") from None
        except (TypeError, ValueError):
            raise _error("次方运算无效") from None
        if isinstance(result, complex):
            raise _error("不支持复数结果")
        return self._check_result(result)

    def _primary(self) -> int | float:
        token = self.current
        if token.kind == "NUM":
            self._advance()
            return token.value
        if token.kind == "LPAREN":
            self._advance()
            self.depth += 1
            if self.depth > MAX_PAREN_DEPTH:
                raise _error("括号嵌套过深")
            value = self._expression()
            self.depth -= 1
            close = self.current
            if close.kind != "RPAREN":
                raise _error("括号不匹配：缺少 ')'", token.pos)
            self._advance()
            return value
        if token.kind == "EOF":
            raise _error("表达式不完整")
        if token.kind == "RPAREN":
            raise _error("括号不匹配：多余的 ')'", token.pos)
        raise _error("运算符位置错误", token.pos)

    @staticmethod
    def _check_result(value: int | float) -> int | float:
        if isinstance(value, complex):
            raise _error("不支持复数结果")
        if isinstance(value, float) and not math.isfinite(value):
            raise _error("结果超出可计算范围")
        if isinstance(value, int) and value.bit_length() > MAX_RESULT_BITS:
            raise _error("结果过大，超出安全显示限制")
        return value


def evaluate(expression: str, base: int = 10) -> int | float:
    """Evaluate an expression safely in the given input base."""
    validate_base(base)
    text = normalize_text(expression).strip()
    if not text:
        raise ExpressionError("表达式为空")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"表达式长度不能超过 {MAX_EXPRESSION_LENGTH} 个字符")
    tokens = _tokenize(text, base)
    parser = _Parser(tokens)
    try:
        return parser.parse()
    except RecursionError:
        raise ExpressionError("表达式嵌套过深") from None


def format_decimal(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ExpressionError("结果超出可计算范围")
    if value == 0:
        return "0"
    if value.is_integer():
        # Avoid showing 4.0 after division such as 8/2.
        return str(int(value))
    return format(value, ".12g")


def _group_binary(digits: str) -> str:
    groups: list[str] = []
    while digits:
        groups.append(digits[-4:])
        digits = digits[:-4]
    return " ".join(reversed(groups))


def format_int(value: int, base: int) -> str:
    validate_base(base)
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if base == 10:
        return sign + str(magnitude)
    if base == 16:
        digits = format(magnitude, "X")
    elif base == 8:
        digits = format(magnitude, "o")
    else:
        digits = format(magnitude, "b")
        digits = _group_binary(digits)
    return sign + BASE_PREFIX[base] + digits


def format_result(value: int | float, base: int) -> str:
    """Format a result in the base it was evaluated in."""
    if isinstance(value, int):
        return format_int(value, base)
    if base != 10 and value.is_integer() and math.isfinite(value):
        return format_int(int(value), base)
    return format_decimal(value)


def convert_bases(value: int | float) -> dict[int, str | None]:
    """Return all four programmer-base representations for a value."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return {base: None for base in SUPPORTED_BASES}
        if value.is_integer():
            integer = int(value)
        else:
            converted: dict[int, str | None] = {
                base: None for base in SUPPORTED_BASES
            }
            converted[10] = format_decimal(value)
            return converted
    elif isinstance(value, int):
        integer = value
    else:
        return {base: None for base in SUPPORTED_BASES}
    return {base: format_int(integer, base) for base in SUPPORTED_BASES}
