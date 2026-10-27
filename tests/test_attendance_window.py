"""Tests isolés des horaires de présence, sans démarrer Streamlit."""
import ast
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


SOURCE = Path(__file__).resolve().parents[1] / "liturgie_app_core.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
FUNCTIONS = {
    "latest_saturday", "attendance_saturday_for_date",
    "attendance_window", "attendance_is_open",
}
NODES = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
CONSTANTS = [
    node for node in TREE.body
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id in
            {"APP_TIMEZONE", "ATTENDANCE_OPEN_TIME", "ATTENDANCE_CLOSE_TIME"}
            for t in node.targets)
]
SCOPE = {"date": date, "datetime": datetime, "time": time,
         "timedelta": timedelta, "ZoneInfo": ZoneInfo}
exec(compile(ast.Module(body=CONSTANTS + NODES, type_ignores=[]), str(SOURCE), "exec"), SCOPE)


class AttendanceWindowTests(unittest.TestCase):
    def test_friday_to_monday_boundaries(self):
        saturday = date(2026, 10, 31)
        start, end = SCOPE["attendance_window"](saturday)
        self.assertEqual(start.isoformat(), "2026-10-30T00:00:00+00:00")
        self.assertEqual(end.isoformat(), "2026-11-02T23:59:59+00:00")
        for moment in (
            datetime(2026, 10, 30, 0, 0, tzinfo=SCOPE["APP_TIMEZONE"]),
            datetime(2026, 11, 2, 23, 59, 59, tzinfo=SCOPE["APP_TIMEZONE"]),
        ):
            self.assertTrue(SCOPE["attendance_is_open"](saturday, moment))
        for moment in (
            datetime(2026, 10, 29, 23, 59, 59, tzinfo=SCOPE["APP_TIMEZONE"]),
            datetime(2026, 11, 3, 0, 0, tzinfo=SCOPE["APP_TIMEZONE"]),
        ):
            self.assertFalse(SCOPE["attendance_is_open"](saturday, moment))

    def test_friday_uses_upcoming_saturday_without_changing_sheet_key(self):
        f = SCOPE["attendance_saturday_for_date"]
        self.assertEqual(f(date(2026, 10, 30)), date(2026, 10, 31))
        self.assertEqual(f(date(2026, 10, 31)), date(2026, 10, 31))
        self.assertEqual(f(date(2026, 11, 2)), date(2026, 10, 31))
        self.assertEqual(f(date(2026, 11, 3)), date(2026, 10, 31))


if __name__ == "__main__":
    unittest.main()
