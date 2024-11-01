"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import operator
import random
import re
from collections.abc import Callable, Generator
from functools import lru_cache
from typing import Any, Self, TypeVar


@lru_cache(128)
def ncr(n: int, r: int) -> int:
    if 0 <= r <= n:
        ntok = 1
        rtok = 1
        r = ((n - r) * (n - r < n)) + (r * (not (n - r < n)))
        for t in range(r):
            ntok *= n - t
            rtok *= t + 1
        return ntok // rtok
    return 0


@lru_cache(256)
def _inner_flattened_cdf_math(quant: int, sides: int, i: int, j: int) -> float:
    x = (((sides - j) / sides) ** i) * ((j / sides) ** (quant - i))
    y = (((sides - j + 1) / sides) ** i) * (((j - 1) / sides) ** (quant - i))
    return ncr(quant, i) * (x - y)


@lru_cache(128)
def _ev_roll_dice_keep_best(quant: int, sides: int, keep: int) -> float:
    outermost_sum = 0
    for k in range(keep):
        middle_sum = 0
        for j in range(1, sides + 1):
            inner_sum = 0
            for i in range(k + 1):
                inner_sum += _inner_flattened_cdf_math(quant, sides, i, j)
            middle_sum += j * inner_sum
        outermost_sum += middle_sum
    return outermost_sum


@lru_cache(128)
def _ev_roll_dice_keep_worst(quant: int, sides: int, keep: int) -> float:
    outermost_sum = 0
    for k in range(1, keep + 1):
        middle_sum = 0
        for j in range(1, sides + 1):
            inner_sum = 0
            for i in range(quant - k + 1):
                inner_sum += _inner_flattened_cdf_math(quant, sides, i, j)
            middle_sum += j * inner_sum
        outermost_sum += middle_sum
    return outermost_sum


__all__ = ["DiceError", "Expression"]

_OP_T = TypeVar("_OP_T")

_OperatorType = Callable[[_OP_T, _OP_T], _OP_T]
OperatorType = _OperatorType[Any]

OPS: dict[str, OperatorType] = {
    "+": operator.add,
    "-": operator.sub,
}

# This needs this type so that a later thing doesn't need type ignores.
# Essentially, we want to do. ROPS.get(thing_to_format)
# and pyright yells about the keytype not being possible even when a default
# is provided. This is dumb.
ROPS: dict[OperatorType | NumberofDice | int, str] = {
    operator.add: "+",
    operator.sub: "-",
}

DIE_COMPONENT_RE = re.compile(
    # 2 digit quantities of dice, and maximum 100 sides
    r"^(?P<quant>[1-9][0-9]?)d(?P<sides>(?:100)|(?:[1-9][0-9]?))"  # #d#
    r"(?:(?P<kd>[v\^])(?P<kdquant>[1-9][0-9]{0,2}))?"  # (optional) v# or ^#
)


class DiceError(Exception):
    def __init__(self, msg: str | None = None, *args: Any):
        self.msg = msg
        super().__init__(msg, *args)


class TooManyDice(DiceError):
    def __init__(self, msg: str | None = None, *args: Any):
        msg = msg or "Whoops, too many dice here"
        super().__init__(msg, *args)


class TooManyKept(DiceError):
    def __init__(self, msg: str | None = None, *args: Any):
        msg = msg or "You can't keep more dice than you rolled."
        super().__init__(msg, *args)

class ExpectedOperator(DiceError):
    def __init__(self, msg: str | None = None, *args: Any):
        self.current = msg
        msg = f"Expected an operator next (Current: {self.current})"
        super().__init__(msg, *args)

class ExpectedNumberOrDie(DiceError):
    def __init__(self, msg: str | None = None, *args: Any):
        self.current = msg
        msg = f"Expected a number or die next (Current: {self.current}"
        super().__init__(msg, *args)

class IncompleteExpression(DiceError):
    def __init__(self, msg: str | None = None, *args: Any):
        self.current = msg
        msg = f"Incomplete Expression: {self.current}"
        super().__init__(msg, *args)

T = TypeVar("T")


def fast_analytic_ev(quant: int, sides: int, low: int, high: int) -> float:
    if high < quant:
        return _ev_roll_dice_keep_best(quant, sides, high)
    if low:
        return _ev_roll_dice_keep_worst(quant, sides, low)

    return quant * (sides + 1) / 2


def fast_roll(quant: int, sides: int, low: int, high: int) -> int:
    numbers = random.choices(range(1, sides + 1), k=quant)
    numbers.sort()
    return sum(numbers[low:high])


class NumberofDice:
    def __init__(
        self,
        quant: int | str,
        sides: int | str,
        kd: str | None = None,
        kdquant: str | None = None,
    ):
        self.quant = int(quant)
        self.sides = int(sides)

        if kd and kdquant:
            mod = int(kdquant)
            if mod > self.quant:
                raise TooManyKept
            self._kd_expr = f"{kd}{kdquant}"
            if kd == "v":
                self.keep_low = min(mod, self.quant)
                self.keep_high = self.quant
            else:
                self.keep_high = min(mod, self.quant)
                self.keep_low = 0
        else:
            self.keep_high = self.quant
            self.keep_low = 0
            self._kd_expr = ""

    def __repr__(self):
        return f"<Die: {self}>"

    def __str__(self):
        return f"{self.quant}d{self.sides}{self._kd_expr}"

    @property
    def high(self) -> int:
        if not self._kd_expr:
            return self.quant * self.sides
        return (self.keep_low or self.keep_high) * self.sides

    @property
    def low(self) -> int:
        if self._kd_expr:
            return self.keep_low or self.keep_high
        return self.quant

    def get_ev(self) -> float:
        return fast_analytic_ev(
            self.quant, self.sides, self.keep_low, self.keep_high
        )

    def verbose_roll(self) -> tuple[int, list[int]]:
        numbers = random.choices(range(1, self.sides + 1), k=self.quant)
        if not self._kd_expr:
            return sum(numbers), list(numbers)

        numbers.sort()
        if self.keep_high < self.quant:
            filtered = numbers[-self.keep_high :]
        else:
            filtered = numbers[: self.keep_low]

        return sum(filtered), list(numbers)

    def full_verbose_roll(self) -> tuple[int, str]:
        parts: list[str] = []
        choices = random.choices(range(1, self.sides + 1), k=self.quant)
        inner_fmt = ", ".join(map(str, choices))
        parts.append(f"{self.quant}d{self.sides} ({inner_fmt})")
        if self._kd_expr:
            if self.keep_high < self.quant:
                choices.sort()
                choices = choices[-self.keep_high :]
                inner_fmt = ", ".join(map(str, choices))
                parts.append(f"-> Highest {self.keep_high} ({inner_fmt})")
            else:
                choices.sort()
                choices = choices[: self.keep_low]
                inner_fmt = ", ".join(map(str, choices))
                parts.append(f"-> Lowest {self.keep_low} ({inner_fmt})")

        total = sum(choices)
        parts.append(f"-> ({total})")
        return total, " ".join(parts)

    def roll(self) -> int:
        low, high = 0, self.quant
        if self._kd_expr:
            if self.keep_high < self.quant:
                low = self.quant - self.keep_high
            else:
                high = self.keep_low

        return fast_roll(self.quant, self.sides, low, high)


def _try_die_or_int(expr: str) -> tuple[NumberofDice | int, str]:
    if m := DIE_COMPONENT_RE.search(expr):
        return NumberofDice(**m.groupdict()), expr[m.end() :]

    if m := re.search(r"^[1-9][0-9]{0,2}", expr):
        return int(m.group()), expr[m.end() :]

    raise DiceError


def _die_or_component_fmt(x: NumberofDice | OperatorType | int, /) -> str:
    return ROPS.get(x) or str(x)


class Expression:
    def __init__(self):
        self._components: list[NumberofDice | OperatorType | int] = []
        self._current_num_dice = 0

    def __repr__(self):
        if self._components:
            return "<Dice Expression '%s'>" % self
        return "<Empty Dice Expression>"

    def __str__(self):
        return " ".join(map(_die_or_component_fmt, self._components))

    def add_dice(self, die: NumberofDice | int) -> None:
        if len(self._components) % 2:
            raise ExpectedOperator(str(self))

        if isinstance(die, NumberofDice):
            n = self._current_num_dice + die.quant
            if n > 1000:
                raise TooManyDice
            self._current_num_dice = n

        self._components.append(die)

    def add_operator(self, op: OperatorType) -> None:
        if not len(self._components) % 2:
            raise ExpectedNumberOrDie(str(self))

        self._components.append(op)

    @staticmethod
    def _group_by_dice(components: list[T]) -> Generator[list[T], Any, Any]:
        start = 0
        for idx, component in enumerate(components):
            if isinstance(component, NumberofDice):
                if start != idx:
                    yield components[start:idx]
                start = idx

        yield components[start:]

    def verbose_roll2(self) -> str:
        total = 0
        parts: list[str] = []
        next_operator = operator.add

        for group in self._group_by_dice(self._components):
            partial_total = 0
            partial_parts: list[str] = []
            dice_part = ""
            op_last = False
            last_op = None

            for component in group:
                if isinstance(component, int):
                    total = next_operator(total, component)
                    partial_total = next_operator(partial_total, component)
                    partial_parts.append(f"{component}")
                    op_last = False
                elif isinstance(component, NumberofDice):
                    amount, verbose_result = component.verbose_roll()
                    total = next_operator(total, amount)
                    partial_total = next_operator(partial_total, amount)
                    partial_parts.append(f"{component}")
                    dice_part = f": {verbose_result} -> {amount}"
                    op_last = False
                else:
                    next_operator = component
                    partial_parts.append(f"{ROPS[next_operator]}")
                    op_last = True

            total += partial_total

            if op_last:
                last_op = partial_parts.pop()

            st = " ".join(partial_parts).strip()
            if dice_part:
                ex = " ".join(partial_parts[1:]).strip()
                parts.append(f"{st}{dice_part} {ex} ({partial_total})")
            else:
                parts.append(f"{st} ({partial_total})")

            if last_op:
                parts.append(last_op)

        return "\n".join(parts).strip()

    def verbose_roll(self) -> tuple[int, str]:
        total = 0
        parts: list[str] = []
        next_operator = operator.add

        partial_total = 0

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
                partial_total = next_operator(partial_total, component)
                parts.append(f"{component}")
            elif isinstance(component, NumberofDice):
                if parts:
                    parts.pop()
                if partial_total:
                    parts.append(f"({partial_total})")
                    partial_total = 0

                amount, verbose_result = component.verbose_roll()
                total = next_operator(total, amount)
                partial_total = next_operator(partial_total, amount)
                parts.append(f"\n{component}: {verbose_result} -> {amount}")
            else:
                next_operator = component
                parts.append(f"{ROPS[next_operator]}")

        if partial_total:
            parts.append(f"({partial_total})")

        return total, " ".join(parts).strip()

    def full_verbose_roll(self) -> tuple[int, str]:
        if not len(self._components) % 2:
            raise IncompleteExpression(str(self))

        total = 0
        parts: list[str] = []
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
                parts.append(f"{component}")
            elif isinstance(component, NumberofDice):
                amount, verbose_result = component.full_verbose_roll()
                total = next_operator(total, amount)
                parts.append(verbose_result)
            else:
                next_operator = component
                parts.append(f"\n{ROPS[next_operator]} ")

        parts.append(f"\n-------------\n= {total}")

        return total, "".join(parts)

    def roll(self) -> int:
        if not len(self._components) % 2:
            raise IncompleteExpression(str(self))
        total = 0
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                total = next_operator(total, component.roll())
            else:
                next_operator = component

        return total

    def get_min(self) -> int:
        if not len(self._components) % 2:
            raise IncompleteExpression(str(self))
        total = 0
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                mod = (
                    component.high
                    if next_operator is operator.sub
                    else component.low
                )
                total = next_operator(total, mod)
            else:
                next_operator = component

        return total

    def get_max(self) -> int:
        if not len(self._components) % 2:
            raise IncompleteExpression(str(self))
        total = 0
        next_operator = operator.add

        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                mod = (
                    component.low
                    if next_operator is operator.sub
                    else component.high
                )
                total = next_operator(total, mod)
            else:
                next_operator = component

        return total

    @classmethod
    def from_str(cls: type[Self], expr: str) -> Self:
        c = 0
        obj = cls()

        while expr := expr.strip():
            if c % 2:
                if op := OPS.get(expr[0], None):
                    assert op is not None, "mypy#8128"  # nosec
                    obj.add_operator(op)
                    expr = expr[1:]
                else:
                    raise IncompleteExpression(str(obj))

            else:
                try:
                    part, expr = _try_die_or_int(expr)
                except DiceError as exc:
                    raise ExpectedNumberOrDie(str(obj)) from exc
                obj.add_dice(part)

            c += 1

        if not (c % 2 or c):
            raise IncompleteExpression(str(obj))

        expr = expr.strip()

        return obj

    def get_ev(self) -> float:
        if not len(self._components) % 2:
            raise IncompleteExpression(str(self))

        total = 0
        next_operator = operator.add

        # Taking a shortcut here. it's "correct enough"
        for component in self._components:
            if isinstance(component, int):
                total = next_operator(total, component)
            elif isinstance(component, NumberofDice):
                total = next_operator(total, component.get_ev())
            else:
                next_operator = component

        return total
