"""Checks the cost model against worked examples on the AWS pricing pages, and against its own arithmetic.

    python -m unittest -v test_model
"""
import unittest

import model
from model import Workload


class PublishedExamples(unittest.TestCase):
    """If these stop passing, either the prices in prices.json or the formulas are wrong."""

    def test_fargate_example_five_x86_tasks_ten_minutes_a_day(self):
        # Fargate pricing page, example 1: 5 tasks, 1 vCPU, 2 GB, 10 minutes a day for 30 days: vCPU 1.01 + memory 0.22.
        self.assertAlmostEqual(model.fargate_cost(5 * 10 * 60 * 30, 1, 2, "x86"), 1.01 + 0.22, delta=0.006)

    def test_fargate_example_same_workload_on_arm(self):
        # Example 2: vCPU 0.81 + memory 0.18.
        self.assertAlmostEqual(model.fargate_cost(5 * 10 * 60 * 30, 1, 2, "arm"), 0.81 + 0.18, delta=0.006)

    def test_app_runner_example_lightweight_api(self):
        # App Runner pricing page: 1 vCPU, 2 GB, one provisioned instance, active 8 hours a day: 25.50 for 30 days.
        # The page rounds each day to cents (0.51 + 0.34 = 0.85) before multiplying; unrounded it is 25.44.
        self.assertAlmostEqual(model.app_runner_cost(24 * 30, 8 * 30, 1, 2), 25.50, delta=0.07)
        self.assertAlmostEqual(model.app_runner_cost(24, 8, 1, 2), 0.85, delta=0.005)

    def test_lambda_example_mobile_backend(self):
        # Lambda pricing page: 3 million requests, 120 ms, 1536 MB, x86, with the free tier: 2.33 + 0.40 = 2.73.
        cost = model.lambda_cost(3_000_000, 120, 1536, "x86", free_tier=True)
        self.assertAlmostEqual(cost["compute"], 2.33, delta=0.006)
        self.assertAlmostEqual(cost["requests"], 0.40, delta=0.001)

    def test_load_balancer_hour_charge_for_a_month(self):
        self.assertAlmostEqual(model.PRICES["alb"]["hour"] * model.HOURS, 16.425, places=3)


class Behaviour(unittest.TestCase):
    def test_lambda_costs_nothing_without_traffic_and_containers_do(self):
        idle = Workload(0)
        self.assertEqual(model.total(model.lambda_function(idle)), 0)
        self.assertGreater(model.total(model.app_runner(idle)), 2)
        self.assertGreater(model.total(model.ecs_express(idle)), 30)

    def test_every_option_costs_more_with_more_traffic(self):
        for name, option in model.OPTIONS.items():
            costs = [model.total(option(Workload(v))) for v in model.VOLUMES]
            self.assertEqual(costs, sorted(costs), name)

    def test_app_runner_floor_is_memory_only(self):
        self.assertAlmostEqual(model.total(model.app_runner(Workload(0))), 0.5 * 0.007 * 730, places=2)

    def test_express_floor_is_task_load_balancer_and_three_addresses(self):
        expected = model.fargate_cost(730 * 3600, 0.25, 0.5) + 0.0225 * 730 + 3 * 0.005 * 730      # one task address, two for the load balancer
        self.assertAlmostEqual(model.total(model.ecs_express(Workload(0))), expected, places=2)

    def test_sharing_the_load_balancer_divides_its_fixed_cost(self):
        alone = model.ecs_express(Workload(0))["load balancer"]
        shared = model.ecs_express(Workload(0), services_on_load_balancer=5)["load balancer"]
        self.assertAlmostEqual(shared, alone / 5, places=6)

    def test_private_subnets_remove_the_address_charges(self):
        private = model.ecs_express(Workload(1_000_000), public_subnets=False)
        self.assertEqual(private["task public IPv4"], 0)
        self.assertLess(private["load balancer"], model.ecs_express(Workload(1_000_000))["load balancer"])

    def test_tasks_follow_the_busiest_minute(self):
        # 50M requests: 38.8 a second in the busy hours, 116 at the peak, 1.75 vCPU of work, 0.15 usable vCPU per task.
        tasks = model.instances_needed(Workload(50_000_000), 0.25, 1)
        self.assertEqual(tasks[True], 12)
        self.assertLessEqual(tasks[False], 2)

    def test_http_api_adds_one_dollar_per_million(self):
        w = Workload(7_000_000)
        self.assertAlmostEqual(model.total(model.lambda_function(w, http_api=True)) - model.total(model.lambda_function(w)), 7.0, places=6)

    def test_at_a_break_even_the_two_options_cost_the_same(self):
        lam, ecs = model.OPTIONS["Lambda, function URL"], model.OPTIONS["ECS Express, 2 tasks"]
        crossing = model.break_even(lam, ecs, duration_ms=500, cpu_ms=15)
        self.assertIsNotNone(crossing)
        w = Workload(crossing, duration_ms=500, cpu_ms=15)
        self.assertAlmostEqual(model.total(lam(w)), model.total(ecs(w)), delta=0.02 * model.total(lam(w)))

    def test_longer_waits_favour_containers(self):
        lam, ecs = model.OPTIONS["Lambda, function URL"], model.OPTIONS["ECS Express, 2 tasks"]
        slow, slower = model.break_even(lam, ecs, duration_ms=500, cpu_ms=15), model.break_even(lam, ecs, duration_ms=1000, cpu_ms=15)
        self.assertLess(slower, slow)


if __name__ == "__main__":
    unittest.main()
