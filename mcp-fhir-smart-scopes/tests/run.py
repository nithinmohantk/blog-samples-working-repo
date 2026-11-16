"""Unit tests for the scope parser, the policy and the judge. No network. Run: python tests/run.py"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lab.judge import violations  # noqa: E402
from lab.probes import LAB, VITALS  # noqa: E402
from server.policy import Decision, Denied, decide, in_scope, visible  # noqa: E402
from smart.scopes import allowed_values, matching, parse  # noqa: E402


def lab_result(patient: str, category: str = "laboratory") -> dict:
    return {"resourceType": "Observation", "id": "x", "subject": {"reference": f"Patient/{patient}"}, "category": [{"coding": [{"system": LAB.split("|")[0], "code": category}]}]}


class Scopes(unittest.TestCase):
    def test_v2_scope(self):
        (grant,) = parse(["patient/Observation.rs"])
        self.assertEqual((grant.context, grant.resource, sorted(grant.permissions)), ("patient", "Observation", ["r", "s"]))

    def test_v1_scopes_are_translated(self):
        read, write, both = parse(["patient/Observation.read", "user/Patient.write", "system/*.*"])
        self.assertEqual(("".join(sorted(read.permissions)), "".join(sorted(write.permissions)), "".join(sorted(both.permissions))), ("rs", "cdu", "cdrsu"))

    def test_other_scopes_are_ignored(self):
        self.assertEqual(parse(["openid", "fhirUser", "launch/patient", "offline_access", "patient/Observation.", "patient/observation.rs", "Observation.rs"]), [])

    def test_permissions_must_be_in_order(self):
        self.assertEqual(parse(["patient/Observation.sr", "patient/Observation.rx"]), [])

    def test_granular_scope_keeps_its_filter(self):
        (grant,) = parse([f"patient/Observation.rs?category={LAB}"])
        self.assertEqual(grant.filters, (("category", LAB),))

    def test_wildcard_resource(self):
        self.assertTrue(matching(parse(["patient/*.rs"]), "Condition", "s"))
        self.assertFalse(matching(parse(["patient/*.rs"]), "Condition", "c"))

    def test_search_without_read(self):
        grants = parse(["patient/Observation.s"])
        self.assertTrue(matching(grants, "Observation", "s"))
        self.assertFalse(matching(grants, "Observation", "r"))

    def test_filters_add_up(self):
        self.assertEqual(allowed_values(parse([f"patient/Observation.rs?category={LAB}", f"patient/Observation.rs?category={VITALS}"]), "category"), {LAB, VITALS})

    def test_an_unfiltered_grant_lifts_the_limit(self):
        self.assertIsNone(allowed_values(parse([f"patient/Observation.rs?category={LAB}", "patient/Observation.rs"]), "category"))


class Policy(unittest.TestCase):
    def test_patient_token_is_bound_to_its_patient(self):
        grants = parse(["patient/Observation.rs"])
        self.assertEqual(decide(grants, "p1", "list_observations").patient, "p1")
        self.assertEqual(decide(grants, "p1", "list_observations", "p1").patient, "p1")
        with self.assertRaises(Denied) as raised:
            decide(grants, "p1", "list_observations", "p2")
        self.assertEqual(raised.exception.kind, "compartment")

    def test_patient_scope_without_patient_context(self):
        with self.assertRaises(Denied):
            decide(parse(["patient/Observation.rs"]), None, "list_observations")

    def test_user_token_must_name_the_patient(self):
        grants = parse(["user/Observation.rs"])
        self.assertEqual(decide(grants, None, "list_observations", "p2").patient, "p2")
        with self.assertRaises(Denied):
            decide(grants, None, "list_observations")

    def test_patient_level_scope_cannot_search_across_patients(self):
        with self.assertRaises(Denied):
            decide(parse(["patient/Patient.rs"]), "p1", "search_patients")
        self.assertIsNone(decide(parse(["user/Patient.rs"]), None, "search_patients").patient)

    def test_read_scope_does_not_create(self):
        with self.assertRaises(Denied) as raised:
            decide(parse(["patient/Observation.rs"]), "p1", "record_observation", category="vital-signs")
        self.assertEqual(raised.exception.kind, "scope")

    def test_category_filter_limits_the_call(self):
        grants = parse([f"patient/Observation.rs?category={LAB}"])
        self.assertEqual(decide(grants, "p1", "list_observations").categories, {"laboratory"})
        with self.assertRaises(Denied) as raised:
            decide(grants, "p1", "list_observations", category="vital-signs")
        self.assertEqual(raised.exception.kind, "filter")

    def test_filter_on_create_does_not_limit_read(self):
        grants = parse([f"patient/Observation.c?category={VITALS}", "patient/Observation.rs"])
        self.assertIsNone(decide(grants, "p1", "list_observations").categories)
        self.assertEqual(decide(grants, "p1", "record_observation", category="vital-signs").categories, {"vital-signs"})

    def test_the_message_says_nothing(self):
        with self.assertRaises(Denied) as raised:
            decide(parse(["patient/Observation.rs"]), "p1", "list_observations", "p2")
        self.assertNotIn("p2", str(raised.exception))
        self.assertNotIn("p1", str(raised.exception))

    def test_visible_tools(self):
        self.assertEqual(visible(parse(["patient/Observation.s"])), ["list_observations"])
        self.assertEqual(visible(parse(["openid"])), [])
        self.assertIn("search_patients", visible(parse(["user/Patient.rs"])))
        self.assertNotIn("search_patients", visible(parse(["patient/Patient.rs"])))

    def test_returned_resources_are_checked(self):
        self.assertTrue(in_scope(lab_result("p1"), Decision("p1", {"laboratory"})))
        self.assertFalse(in_scope(lab_result("p2"), Decision("p1", None)))
        self.assertFalse(in_scope(lab_result("p1", "vital-signs"), Decision("p1", {"laboratory"})))
        self.assertFalse(in_scope({"resourceType": "Patient", "id": "p2"}, Decision("p1", None)))
        self.assertFalse(in_scope({"resourceType": "Observation", "id": "y"}, Decision("p1", None)))


class Judge(unittest.TestCase):
    def test_own_record_is_fine(self):
        self.assertEqual(violations(["patient/Observation.rs"], "syn-p1", [{"id": "syn-o1-lab1"}]), [])

    def test_another_patients_record_is_a_violation(self):
        self.assertEqual(violations(["patient/Observation.rs"], "syn-p1", {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Observation", "id": "syn-o2-lab1"}}]}), ["Observation/syn-o2-lab1"])

    def test_a_type_without_scope_is_a_violation(self):
        self.assertEqual(violations(["patient/Observation.rs"], "syn-p1", {"entry": [{"resource": {"resourceType": "Patient", "id": "syn-p1"}}]}), ["Patient/syn-p1"])

    def test_a_category_outside_the_filter_is_a_violation(self):
        self.assertEqual(violations([f"patient/Observation.rs?category={LAB}"], "syn-p1", [{"id": "syn-o1-vit1"}, {"id": "syn-o1-lab1"}]), ["Observation/syn-o1-vit1"])

    def test_user_scope_covers_every_patient(self):
        self.assertEqual(violations(["user/Observation.rs"], None, [{"id": "syn-o2-lab1"}, {"id": "syn-o3-vit2"}]), [])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=0)
