"""Robust statistics: the median and MAD cannot be talked out of their answer by an outlier."""

from __future__ import annotations

import math

import numpy as np
import pytest

from meridian.quality.robust import (
    MAD_SCALE,
    classical_zscores,
    hampel_filter,
    mad,
    median,
    robust_zscores,
    rolling_classical_z,
    rolling_robust_z,
)


def test_mad_is_a_consistent_estimator_of_sigma_for_normal_data():
    sample = np.random.default_rng(1).normal(0, 2.0, 50_000)
    assert mad(sample.tolist()) == pytest.approx(2.0, rel=0.02)
    assert mad([1, 2, 3, 4, 100], scaled=False) == 1.0
    assert pytest.approx(1 / 0.6745, rel=1e-3) == MAD_SCALE


def test_one_outlier_masks_itself_under_the_classical_score_but_not_the_robust_one():
    values = [0.01, -0.012, 0.008, -0.009, 0.011, -0.01, 0.009, -0.011, 0.4]
    classical = classical_zscores(values)[-1]
    robust = robust_zscores(values)[-1]
    assert classical < 3  # the outlier inflated the standard deviation it is judged by
    assert robust > 10  # while the robust score still sees a fifteen-sigma event


def test_the_median_ignores_half_the_sample_being_garbage():
    clean = [1.0, 1.1, 0.9, 1.05, 0.95]
    contaminated = median([*clean, 1000000000.0, 1000000000.0, 1000000000.0, 1000000000.0])
    assert min(clean) <= contaminated <= max(clean)  # four garbage values out of nine move it one rank
    assert sum(clean + [1e9] * 4) / 9 > 4e8  # the mean is destroyed by a single one


def test_empty_inputs():
    with pytest.raises(ValueError):
        median([])
    with pytest.raises(ValueError):
        mad([])
    assert robust_zscores([]) == []
    assert classical_zscores([1.0]) == [0.0]
    assert classical_zscores([2.0, 2.0]) == [0.0, 0.0]


def test_a_zero_mad_scores_departures_as_infinite():
    scores = robust_zscores([5.0, 5.0, 5.0, 5.0, 6.0])
    assert scores[0] == 0.0
    assert scores[-1] == math.inf


def test_rolling_scores_look_only_backwards():
    values = [0.0] * 30 + [1.0] + [0.0] * 5
    scores = rolling_robust_z(values, window=20, min_periods=10)
    assert scores[:10] == [None] * 10
    assert scores[30] == math.inf  # the jump against a flat window
    changed = rolling_robust_z([*values[:30], 5.0, *values[31:]], window=20, min_periods=10)
    assert changed[:30] == scores[:30]  # changing day 30 cannot change the score of any earlier day


def test_rolling_robust_score_finds_a_spike_in_noisy_data():
    rng = np.random.default_rng(4)
    values = rng.normal(0, 0.01, 200).tolist()
    values[150] = 0.15
    scores = rolling_robust_z(values, window=60, min_periods=20)
    flagged = [index for index, score in enumerate(scores) if score is not None and abs(score) > 8]
    assert flagged == [150]


def test_rolling_classical_score_for_comparison():
    values = [0.01, -0.01] * 20 + [0.5]
    scores = rolling_classical_z(values, window=30, min_periods=10)
    assert scores[0] is None
    assert scores[-1] is not None and scores[-1] > 10
    flat = rolling_classical_z([1.0] * 15, window=10, min_periods=5)
    assert flat[-1] == 0.0


def test_rolling_window_validation():
    with pytest.raises(ValueError):
        rolling_robust_z([1.0, 2.0], window=2)


def test_hampel_filter_replaces_the_bad_point_with_its_neighbourhood_median():
    values = [10.0, 10.1, 9.9, 10.05, 30.0, 10.0, 9.95, 10.1]
    cleaned, replaced = hampel_filter(values, window=5, threshold=3.0)
    assert replaced == [4]
    assert cleaned[4] == pytest.approx(10.0, abs=0.1)
    assert cleaned[:4] == values[:4]
