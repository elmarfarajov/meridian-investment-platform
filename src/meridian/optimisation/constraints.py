"""The mandate, compiled into constraints an optimiser can respect.

The rules that check a portfolio after the fact (Day 6) are the same rules the
optimiser must respect before it proposes one. Most of them compile exactly:

* a **weight** of the holdings a filter selects is a linear function of the
  asset weights - look-through included, because a fund's constituents are a
  fixed share of the fund - so "cash between 1% and 10%" and "tobacco inside
  the funds at most 0.5%" are linear constraints;
* **"max weight by"** a group is one linear constraint per group: every issuer
  (or sector, or currency) at most its limit;
* **"no holdings"** removes what it selects from the problem: never bought,
  sold in full if held. Pinning a weight at zero with an equality would leave
  the feasible set without an interior, which an interior-point solver cannot
  work with, so an exclusion shapes the variables instead of constraining them;
* **tracking error** and **volatility** limits are second-order cone
  constraints on the factor model;
* **active share** is convex, so a ceiling compiles as it stands, and a floor
  compiles through a linear function beneath it that the rebalancer supplies
  and refines in rounds (the convex-concave procedure).

What does not compile - a count of holdings, the UCITS concentration sum - is
not convex (nor continuous) and is left to the post-trade check, which runs
the Day 6 engine on the proposed portfolio and reports any rule it would break.

Every limit is met a small buffer inside, so that the compliance engine,
measuring the proposed portfolio its own way, finds it inside too.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import cvxpy as cp
import numpy as np

from ..compliance.engine import matches
from ..compliance.language import Bound, Mandate, MaxGroupWeight, Metric, NoHoldings, Rule, WeightOf
from ..compliance.snapshot import Holding
from .assets import TradableAsset

CASH_KEY = "CASH.USD"


@dataclass(frozen=True)
class Piece:
    """A slice of the portfolio: an asset, or a constituent of a fund, with the share of the asset it is."""

    asset_index: int  # -1 for cash
    share: float
    holding: Holding


@dataclass
class CompiledMandate:
    constraints: list[cp.Constraint]
    compiled: list[str]
    skipped: list[str]
    soft_slack: cp.Expression | None = None  # total violation of soft rules, penalised in the objective


def pieces(assets: Sequence[TradableAsset], look_through: Mapping[str, Sequence[Holding]], expand: bool) -> list[Piece]:
    output: list[Piece] = []
    for index, asset in enumerate(assets):
        constituents = look_through.get(asset.asset_id) if expand else None
        if constituents:
            output.extend(Piece(index, constituent.weight, constituent) for constituent in constituents)
        else:
            output.append(Piece(index, 1.0, Holding(asset.asset_id, 0.0, dict(asset.attributes))))
    output.append(
        Piece(-1, 1.0, Holding(CASH_KEY, 0.0, {"asset_class": "cash", "currency": "USD", "issuer": "cash USD"}))
    )
    return output


def _expression(selected: list[Piece], weights: cp.Expression, cash: cp.Expression) -> cp.Expression:
    total: cp.Expression = cp.Constant(0.0)
    per_asset: dict[int, float] = defaultdict(float)
    for piece in selected:
        per_asset[piece.asset_index] += piece.share
    for index, share in per_asset.items():
        total = total + share * (cash if index == -1 else weights[index])
    return total


def _bounded(
    expression: cp.Expression, bound: Bound, slack: cp.Expression | None, buffer: float = 0.0
) -> list[cp.Constraint]:
    """The bound as constraints, met ``buffer`` inside each side; a soft rule's slack loosens it."""
    loosen = 0 if slack is None else slack
    constraints: list[cp.Constraint] = []
    if bound.exact and bound.upper is not None:
        if slack is None:
            return [expression == float(bound.upper)]
        return [cp.abs(expression - float(bound.upper)) <= slack]
    if bound.upper is not None:
        constraints.append(expression <= max(float(bound.upper) - buffer, 0.0) + loosen)
    if bound.lower is not None:
        constraints.append(expression >= float(bound.lower) + buffer - loosen)
    return constraints


def active_share_rule(mandate: Mandate, include_soft: bool = True) -> tuple[str, float] | None:
    """The rule id and floor of an active-share lower bound, if the mandate has one."""
    for rule in mandate.rules:
        measure = rule.measure
        if rule.severity == "soft" and not include_soft:
            continue
        if isinstance(measure, Metric) and measure.name == "active_share" and rule.bound.lower is not None:
            return rule.rule_id, float(rule.bound.lower)
    return None


def compile_mandate(
    mandate: Mandate,
    assets: Sequence[TradableAsset],
    weights: cp.Expression,
    cash: cp.Expression,
    look_through: Mapping[str, Sequence[Holding]],
    *,
    tracking_error: cp.Expression | None = None,
    volatility: cp.Expression | None = None,
    active_share: cp.Expression | None = None,
    active_share_minorant: cp.Expression | None = None,
    include_soft: bool = True,
    buffer: float = 0.0,
) -> CompiledMandate:
    """Constraints for every rule that compiles; soft rules get a slack the objective penalises.

    Active share is convex, so a ceiling on it compiles directly; a floor needs
    ``active_share_minorant``, a linear function below it (see
    :mod:`.rebalance`), and is skipped without one.
    """
    constraints: list[cp.Constraint] = []
    compiled: list[str] = []
    skipped: list[str] = []
    slacks: list[cp.Variable] = []
    direct = pieces(assets, look_through, expand=False)
    expanded = pieces(assets, look_through, expand=True)

    def slack_for(rule: Rule) -> cp.Variable | None:
        if rule.severity == "hard":
            return None
        variable = cp.Variable(nonneg=True, name=f"slack_{rule.rule_id}")
        slacks.append(variable)
        return variable

    for rule in mandate.rules:
        if rule.severity == "soft" and not include_soft:
            continue
        measure = rule.measure
        if isinstance(measure, NoHoldings):
            compiled.append(rule.rule_id)  # applied by exclusion: see excluded_assets
        elif isinstance(measure, WeightOf):
            source = expanded if measure.look_through else direct
            selected = [piece for piece in source if matches(measure.filter, piece.holding)]
            if not selected:
                compiled.append(rule.rule_id)
                continue
            constraints += _bounded(_expression(selected, weights, cash), rule.bound, slack_for(rule), buffer)
            compiled.append(rule.rule_id)
        elif isinstance(measure, MaxGroupWeight):
            source = expanded if measure.look_through else direct
            groups: dict[str, list[Piece]] = defaultdict(list)
            for piece in source:
                label = piece.holding.attribute(measure.group_by)
                if label is not None and matches(measure.filter, piece.holding):
                    groups[str(label)].append(piece)
            slack = slack_for(rule)
            for members in groups.values():
                ceiling = Bound(upper=rule.bound.upper)
                constraints += _bounded(_expression(members, weights, cash), ceiling, slack, buffer)
            compiled.append(rule.rule_id)
        elif isinstance(measure, Metric) and measure.name == "tracking_error" and tracking_error is not None:
            constraints += _bounded(tracking_error, rule.bound, slack_for(rule), buffer)
            compiled.append(rule.rule_id)
        elif isinstance(measure, Metric) and measure.name == "volatility" and volatility is not None:
            constraints += _bounded(volatility, rule.bound, slack_for(rule), buffer)
            compiled.append(rule.rule_id)
        elif (
            isinstance(measure, Metric)
            and measure.name == "active_share"
            and (
                (rule.bound.lower is None and active_share is not None)
                or (rule.bound.lower is not None and active_share_minorant is not None)
            )
        ):
            slack = slack_for(rule)
            if rule.bound.upper is not None and active_share is not None:
                constraints += _bounded(active_share, Bound(upper=rule.bound.upper), slack, buffer)
            if rule.bound.lower is not None and active_share_minorant is not None:
                constraints += _bounded(active_share_minorant, Bound(lower=rule.bound.lower), slack, buffer)
            compiled.append(rule.rule_id)
        else:
            skipped.append(rule.rule_id)
    total_slack = sum(slacks) if slacks else None
    return CompiledMandate(constraints, compiled, skipped, total_slack)  # type: ignore[arg-type]


def excluded_assets(
    mandate: Mandate, assets: Sequence[TradableAsset], look_through: Mapping[str, Sequence[Holding]]
) -> dict[int, str]:
    """Asset index -> the "no holdings" rule that excludes it (a fund, if any constituent is excluded)."""
    output: dict[int, str] = {}
    for rule in mandate.rules:
        measure = rule.measure
        if not isinstance(measure, NoHoldings):
            continue
        for piece in pieces(assets, look_through, expand=measure.look_through):
            if piece.asset_index >= 0 and matches(measure.filter, piece.holding):
                output.setdefault(piece.asset_index, rule.rule_id)
    return output


def lookthrough_matrix(assets: Sequence[TradableAsset], keys: Sequence[str]) -> np.ndarray:
    """n x C: each asset's loading on each coverage asset of the risk model."""
    index = {key: position for position, key in enumerate(keys)}
    matrix = np.zeros((len(assets), len(keys)))
    for row, asset in enumerate(assets):
        for key, share in asset.risk_row.items():
            matrix[row, index[key]] += share
    return matrix
