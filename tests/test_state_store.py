import unittest
from copy import deepcopy
from unittest.mock import patch

from state_store import StateConflictError, load_state_record, save_state_if_revision


class FakeResponse:
    def __init__(self, data, ok=True):
        self._data = data
        self.ok = ok

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP error")

    def json(self):
        return deepcopy(self._data)


class FakeBackend:
    def __init__(self):
        self.state = {"history": [{"date": "2026-10-04"}]}
        self.revision = 0
        self.updated_at = "2026-09-15T08:00:00+00:00"

    def get(self, endpoint, headers=None, params=None, timeout=None):
        self.assert_select(params)
        return FakeResponse([
            {
                "state_json": deepcopy(self.state),
                "revision": self.revision,
                "updated_at": self.updated_at,
            }
        ])

    @staticmethod
    def assert_select(params):
        assert params["select"] == "state_json,revision,updated_at"

    def patch(self, endpoint, headers=None, params=None, json=None, timeout=None):
        expected = int(str(params["revision"]).removeprefix("eq."))
        if expected != self.revision:
            return FakeResponse([])
        self.state = deepcopy(json["state_json"])
        self.revision = int(json["revision"])
        self.updated_at = str(json["updated_at"])
        return FakeResponse([{"revision": self.revision, "updated_at": self.updated_at}])


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.url = "https://example.supabase.co"
        self.key = "service-secret"
        self.state_key = "programme-liturgique-principal"

    def test_load_returns_state_and_revision(self):
        with patch("state_store.requests.get", side_effect=self.backend.get):
            state, revision, updated_at = load_state_record(self.url, self.key, self.state_key)
        self.assertEqual(revision, 0)
        self.assertEqual(state, self.backend.state)
        self.assertTrue(updated_at)

    def test_second_writer_with_stale_revision_is_rejected(self):
        with patch("state_store.requests.get", side_effect=self.backend.get), patch(
            "state_store.requests.patch", side_effect=self.backend.patch
        ):
            state_a, revision_a, _ = load_state_record(self.url, self.key, self.state_key)
            state_b, revision_b, _ = load_state_record(self.url, self.key, self.state_key)

            state_a["writer"] = "A"
            new_revision = save_state_if_revision(
                self.url, self.key, self.state_key, state_a, revision_a
            )
            self.assertEqual(new_revision, 1)
            self.assertEqual(self.backend.state["writer"], "A")

            state_b["writer"] = "B"
            with self.assertRaises(StateConflictError):
                save_state_if_revision(
                    self.url, self.key, self.state_key, state_b, revision_b
                )

            self.assertEqual(self.backend.revision, 1)
            self.assertEqual(self.backend.state["writer"], "A")

    def test_next_write_after_reload_succeeds(self):
        with patch("state_store.requests.get", side_effect=self.backend.get), patch(
            "state_store.requests.patch", side_effect=self.backend.patch
        ):
            first, revision, _ = load_state_record(self.url, self.key, self.state_key)
            first["step"] = 1
            save_state_if_revision(self.url, self.key, self.state_key, first, revision)

            second, revision, _ = load_state_record(self.url, self.key, self.state_key)
            second["step"] = 2
            saved_revision = save_state_if_revision(
                self.url, self.key, self.state_key, second, revision
            )

            self.assertEqual(saved_revision, 2)
            self.assertEqual(self.backend.state["step"], 2)


if __name__ == "__main__":
    unittest.main()
