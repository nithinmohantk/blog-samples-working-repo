"""Arithmetic for an agent tool without eval().

An agent passes model-generated text to its tools, so a calculator built on
eval() runs whatever the model (or a prompt-injected document) writes. This
evaluator walks the parsed expression and allows numbers, + - * / // % **,
unary signs and parentheses only.
"""

from __future__ import annotations

import ast
import operator

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
MAX_EXPONENT = 100
MAX_LENGTH = 200


def evaluate(expression: str) -> float:
    if len(expression) > MAX_LENGTH:
        raise ValueError("expression too long")
    tree = ast.parse(expression.replace(",", ""), mode="eval")

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError("exponent too large")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](walk(node.operand))
        raise ValueError(f"unsupported element: {type(node).__name__}")

    return walk(tree)


def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression such as (4830000 - 4200000) / 4200000 * 100."""
    try:
        result = evaluate(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        return f"Error: {exc}"
    return f"{result:.10g}"
