"""Parity against archived IEEE Access results and API input safeguards."""
import json
from pathlib import Path
import unittest
from fastapi.testclient import TestClient
from app import app
from simcore import MODEL_VERSION, run_model

REFERENCE = json.loads(Path(__file__).with_name("paper_reference.json").read_text())

class PaperParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_model({}, seed=42, with_sensitivity=False)
        cls.scaled = run_model({"s0_spot":50,"s0_mep":90}, seed=42, with_sensitivity=False)

    def test_current_calibration(self):
        self.assertEqual(self.result["params_used"]["flat_s0"],67)
        self.assertEqual(self.result["params_used"]["n_paths"],5000)
        self.assertEqual(self.result["model_version"],MODEL_VERSION)

    def test_five_policy_values_match_archived_paper(self):
        self.assertTrue("policy_comparison" in self.result)
        self.assertEqual(set(self.result["policy_comparison"]),set(REFERENCE["regimes"]))
        for policy,assets in REFERENCE["regimes"].items():
            for asset,expected in assets.items():
                row=self.result["policy_comparison"][policy][asset]
                for field,value in expected.items():
                    public=field+"_musd" if field not in ("exercise_rate","mean_exercise_time") else field
                    self.assertAlmostEqual(row[public],value/1e6 if public.endswith("_musd") else value,places=6,msg=f"{policy}/{asset}/{field}")

    def test_waiting_premium_excludes_avoided_losses(self):
        self.assertTrue("policy_comparison" in self.result)
        for assets in self.result["policy_comparison"].values():
            for row in assets.values():
                self.assertAlmostEqual(row["pure_deferral_premium_musd"],row["option_value_musd"]-max(row["immediate_npv_musd"],0),places=5)
                self.assertAlmostEqual(row["gain_vs_forced_immediate_musd"],row["pure_deferral_premium_musd"]+row["avoided_negative_npv_musd"],places=5)

    def test_positive_npv_spot_waits_and_supported_mep_invests_now(self):
        self.assertTrue("policy_comparison" in self.scaled)
        policies=self.scaled["policy_comparison"]
        for asset in ("pv","joint"):
            for key in ("spot_only","switching_with_restitution"):
                row=policies[key][asset]
                self.assertGreater(row["immediate_npv_musd"],0)
                self.assertGreater(row["pure_deferral_premium_musd"],0)
                self.assertGreater(row["mean_exercise_time"],0)
            for key in ("fixed_mep_no_restitution","switching_no_restitution"):
                row=policies[key][asset]
                self.assertAlmostEqual(row["pure_deferral_premium_musd"],0,places=6)
                self.assertEqual(row["exercise_rate"],1)
                self.assertEqual(row["mean_exercise_time"],0)
        self.assertAlmostEqual(policies["spot_only"]["pv"]["pure_deferral_premium_musd"],1.326877,places=6)
        self.assertAlmostEqual(policies["switching_with_restitution"]["joint"]["pure_deferral_premium_musd"],0.599449,places=6)
        self.assertNotEqual(self.result["run_id"],self.scaled["run_id"])

    def test_net_operating_values_match_paper(self):
        for asset,expected in REFERENCE["operating"].items():
            row=self.result["switching"][asset]
            self.assertAlmostEqual(row["switch_new_musd"],expected["switch_new_1yr"]/1e6,places=6)
            self.assertAlmostEqual(row["premium_new_musd"],expected["premium_new"]/1e6,places=6)

    def test_ledger_preserves_post_horizon_liability(self):
        for asset in ("pv","bess_energy","joint"):
            self.assertIn("settlement",self.result["switching"][asset])
            ledger=self.result["switching"][asset]["settlement"]
            self.assertTrue(ledger["enabled"])
            self.assertLess(ledger["max_accounting_error_usd"],1e-5)
            self.assertGreater(ledger["mean_tail_repayment_pv_usd"],0)
            self.assertEqual(len(ledger["mean_annual_repayment_usd"]),17)

    def test_selected_policy_diagnostics(self):
        dist=self.result["diagnostics"]["distributions"]
        self.assertAlmostEqual(dist["dual_switching"]["joint"]["zero_mass"],0.6978,places=6)
        self.assertEqual(self.result["diagnostics"]["continuation"]["dual_switching"]["joint"]["n_itm"],1304)

class ApiTests(unittest.TestCase):
    def test_meta_does_not_expose_manuscript_download(self):
        client=TestClient(app)
        meta=client.get("/api/meta")
        self.assertEqual(meta.status_code,200)
        self.assertIn("policy_comparison",meta.json()["paper_baseline"])
        self.assertNotIn("paper_pdf_url", meta.json())
        self.assertEqual(client.get("/api/download-paper").status_code,404)

    def test_nonfinite_inputs_are_rejected(self):
        for value in (float("nan"),float("inf")):
            with self.assertRaises(ValueError):
                run_model({"r":value},with_sensitivity=False)

if __name__=="__main__":
    unittest.main()
