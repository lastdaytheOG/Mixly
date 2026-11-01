import unittest

from mixly.planner import fit
from mixly.scan import Found


def item(name, size):
    return Found(name, name, name, size, "ready")


class PlannerTests(unittest.TestCase):
    def test_everything_fits(self):
        chosen, left = fit([item("a", 10), item("b", 20)], 1000)
        self.assertEqual({entry.id for entry in chosen}, {"a", "b"})
        self.assertEqual(left, [])

    def test_takes_the_largest_that_fit(self):
        chosen, left = fit([item("small", 10), item("big", 80), item("huge", 500)], 100)
        self.assertEqual([entry.id for entry in chosen], ["big", "small"])
        self.assertEqual([entry.id for entry in left], ["huge"])

    def test_leaves_headroom_for_each_item(self):
        chosen, left = fit([item("a", 100)], 104)
        self.assertEqual(chosen, [])
        self.assertEqual([entry.id for entry in left], ["a"])
        self.assertEqual(len(fit([item("a", 100)], 105)[0]), 1)

    def test_your_real_numbers(self):
        sizes = [3.8, 1.1, 0.4, 2.1, 6.5, 6.0, 0.6, 8.0, 0.3, 11.2, 13.6, 2.1]
        items = [item(str(index), int(size * 1024 ** 3)) for index, size in enumerate(sizes)]
        chosen, left = fit(items, int(49.4 * 1024 ** 3))
        used = sum(entry.size for entry in chosen) * 1.05
        self.assertLessEqual(used, 49.4 * 1024 ** 3)
        self.assertTrue(left)
