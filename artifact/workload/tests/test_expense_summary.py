import tempfile
import unittest
from pathlib import Path

from src.expense_summary import summarize


class ExpenseSummaryTests(unittest.TestCase):
    def summarize_rows(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            path.write_text("category,kind,amount\n" + rows, encoding="utf-8")
            return summarize(path)

    def test_charges_are_added(self):
        self.assertEqual(self.summarize_rows("food,charge,10.25\nfood,charge,2.75\n"),
                         {"food": "13.00"})

    def test_refund_is_subtracted(self):
        self.assertEqual(self.summarize_rows("food,charge,120.00\nfood,refund,20.00\n"),
                         {"food": "100.00"})

    def test_refund_only_category_can_be_negative(self):
        self.assertEqual(self.summarize_rows("travel,refund,5.50\n"),
                         {"travel": "-5.50"})

    def test_zero_and_empty_input(self):
        self.assertEqual(self.summarize_rows("food,charge,0.00\n"), {"food": "0.00"})
        self.assertEqual(self.summarize_rows(""), {})

    def test_invalid_rows_are_rejected(self):
        for row in ["food,charge,-1.00\n", "food,other,1.00\n",
                    "food,charge,NaN\n", "food,charge,Infinity\n",
                    "food,charge,1.001\n", ",charge,1.00\n"]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.summarize_rows(row)


if __name__ == "__main__":
    unittest.main()

