"""Accounting and timing checks for the annual Balance MEP approximation."""
from dataclasses import replace
import unittest

import numpy as np

from lsmc_switching_cases import (CaseParams, saldo_balance, saldo_installments,
                                  settlement_discount, net_mep_revenue,
                                  switching_generic, _basis, _fit)
from lsmc_switching_cases import run_all, trivariate_gbm
import lsmc_switching_cases as model


class SaldoMEPTests(unittest.TestCase):
    def test_deferral_only_reports_fixed_regime_immediate_alternative(self):
        base = replace(CaseParams().base, n_paths=64, t_years=4,
                       s0_spot=1000., s0_mep=1200.,
                       mu_spot=0., mu_mep=0., sigma_spot=0., sigma_mep=0.)
        p = replace(CaseParams(), base=base, restitution=False,
                    mu_p=0., sigma_p=0.)
        result = run_all(p)
        for regime, price in (('spot_only', base.s0_spot),
                              ('fixed_mep', base.s0_mep)):
            row = (result['regime_comparison']['spot_only']['pv'] if regime == 'spot_only'
                   else result['fixed_mep_investment']['pv'])
            self.assertIn('pure_deferral_premium', row,
                          'Fixed-regime waiting must be reported separately from switching')
            years = np.arange(base.t_years + 1)
            expected = ((base.gen_annual_mwh * base.fpm * price - base.om_annual)
                        * np.exp(-base.r * years).sum()
                        + base.salvage_frac * base.ci * np.exp(-base.r * base.t_years)
                        - base.ci)
            self.assertAlmostEqual(row['immediate_npv'], expected, places=6)
            self.assertAlmostEqual(row['option_value'], expected, places=6)
            self.assertAlmostEqual(row['pure_deferral_premium'], 0., places=6)
            self.assertEqual(row['exercise_rate'], 1.)
            self.assertEqual(row['mean_exercise_time'], 0.)

    def test_deferral_excludes_losses_avoided_by_not_investing(self):
        self.assertTrue(hasattr(model, 'deferral_metrics'),
                        'Missing decomposition of waiting and avoided losses')
        metrics = model.deferral_metrics(3.0, -5.0)
        self.assertEqual(metrics['immediate_decision_value'], 0.0)
        self.assertEqual(metrics['pure_deferral_premium'], 3.0)
        self.assertEqual(metrics['gain_vs_forced_immediate'], 8.0)
        self.assertEqual(metrics['avoided_negative_npv'], 5.0)

    def test_deferral_subtracts_positive_immediate_alternative(self):
        self.assertTrue(hasattr(model, 'deferral_metrics'),
                        'Missing decomposition of waiting and immediate investment')
        metrics = model.deferral_metrics(3.0, 1.0)
        self.assertEqual(metrics['immediate_npv'], 1.0)
        self.assertEqual(metrics['immediate_decision_value'], 1.0)
        self.assertEqual(metrics['pure_deferral_premium'], 2.0)
        self.assertEqual(metrics['gain_vs_forced_immediate'], 2.0)
        self.assertEqual(metrics['avoided_negative_npv'], 0.0)

    def test_deferral_is_zero_when_immediate_exercise_has_equal_value(self):
        self.assertTrue(hasattr(model, 'deferral_metrics'),
                        'Missing zero timing-premium boundary')
        metrics = model.deferral_metrics(1.0, 1.0)
        self.assertEqual(metrics['pure_deferral_premium'], 0.0)

    def test_twelve_signed_installments(self):
        balances = np.array([120.0, -240.0, 0.0])
        installments = saldo_installments(balances)
        self.assertEqual(installments.shape, (3, 12))
        np.testing.assert_allclose(installments.sum(axis=-1), balances)
        np.testing.assert_allclose(installments[0], 10.0)
        np.testing.assert_allclose(installments[1], -20.0)

    def test_charging_sign_and_excluded_nonenergy_items(self):
        p = CaseParams()
        xs, xm = np.array([25.0]), np.array([45.0])
        pv = p.base.gen_annual_mwh * p.base.fpm * 20.0
        battery = p.e_dis_annual * (110 - 85) - p.e_dis_annual / p.bess_eff * (35 - 15)
        np.testing.assert_allclose(saldo_balance(p, xs, xm, 'pv'), pv)
        np.testing.assert_allclose(saldo_balance(p, xs, xm, 'bess_energy'), battery)
        changed = replace(p, synergy_revenue=.75, bess_om=999999, s0_p=999999)
        np.testing.assert_allclose(saldo_balance(changed, xs, xm, 'joint'), pv + battery)

    def test_settlement_after_spot_and_after_terminal_date(self):
        r = .05
        # MEP at 0, spot at 1, MEP at terminal date 2: the final debt pays in year 3.
        regimes = np.array([1, 0, 1])
        spread = np.array([120.0, 500.0, -240.0])
        balances = np.where(regimes == 1, spread, 0.0)
        gross = np.where(regimes == 1, 1000 + spread, 1000)
        actual_pv = sum(gross * np.exp(-r * np.arange(3)))
        for t, balance in enumerate(balances):
            actual_pv -= sum(saldo_installments(balance) * np.exp(-r * (t + np.arange(1, 13)/12)))
        net = gross - settlement_discount(r) * balances
        self.assertAlmostEqual(actual_pv, sum(net * np.exp(-r * np.arange(3))), places=10)
        self.assertEqual(balances[1], 0)
        self.assertNotEqual(saldo_installments(balances[0]).sum(), 0)
        self.assertNotEqual(saldo_installments(balances[-1]).sum(), 0)

    def test_zero_discount_full_restitution_equals_spot(self):
        p = replace(CaseParams(), base=replace(CaseParams().base, r=0))
        self.assertEqual(settlement_discount(0), 1)
        np.testing.assert_allclose(net_mep_revenue(p, np.array([150., 70.]),
                                                  np.array([50., -30.])), [100., 100.])

    def test_cpi_adjustment_in_real_numeraire(self):
        real = saldo_installments(1200.0)
        cpi = np.exp(.04 * np.arange(1, 13)/12)
        np.testing.assert_allclose((real * cpi) / cpi, real)

    def test_initial_permanence_is_not_waived(self):
        p = replace(CaseParams(), base=replace(CaseParams().base, n_paths=60, t_years=4, r=0))
        cols = lambda t: [np.ones(60)]
        revenue = {0: lambda t: np.full(60, 10.), 1: lambda t: np.zeros(60)}
        values, fitted, _ = switching_generic(p, revenue, cols, 4, 0)
        np.testing.assert_allclose(values[1], 10., atol=1e-10)
        np.testing.assert_allclose(fitted[0][1], 10., atol=1e-10)

    def test_scaled_regression_retains_small_energy_terms(self):
        rng = np.random.default_rng(7)
        cols = [rng.uniform(10, 50, 200), rng.uniform(20, 70, 200),
                rng.uniform(50000, 200000, 200)]
        target = _basis(cols) @ np.array([2., 3., -4., .001, .02, .03, 1e-10, .04, 1e-5, 1e-5])
        np.testing.assert_allclose(_fit(target, cols), target, rtol=1e-10, atol=1e-8)

    def test_no_restitution_preserves_gross_revenue(self):
        p = replace(CaseParams(), restitution=False)
        np.testing.assert_allclose(net_mep_revenue(p, np.array([150., 70.]),
                                                  np.array([50., -30.])), [150., 70.])

    def test_no_restitution_has_no_liability_or_repayments(self):
        p = replace(CaseParams(), restitution=False,
                    base=replace(CaseParams().base, n_paths=64, t_years=4))
        result = run_all(p)
        for asset in ('pv', 'bess_energy', 'joint'):
            ledger = result[asset]['settlement']
            self.assertFalse(ledger['enabled'])
            self.assertEqual(ledger['mean_repayments_pv_usd'], 0)
            np.testing.assert_array_equal(ledger['mean_annual_accrual_usd'], 0)
            self.assertLess(ledger['max_accounting_error_usd'], 1e-5)

    def test_restitution_toggle_preserves_price_paths(self):
        p = replace(CaseParams(), base=replace(CaseParams().base, n_paths=64, t_years=4))
        for with_debt, without_debt in zip(trivariate_gbm(p), trivariate_gbm(replace(p, restitution=False))):
            np.testing.assert_array_equal(with_debt, without_debt)


if __name__ == '__main__':
    unittest.main()
