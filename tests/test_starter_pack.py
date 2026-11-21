"""Тесты целостности стартового набора (starter_pack) для проекта «Спасти хакатон».

Проверяют эталонные данные в fixtures/, работу скрипта reset.py,
сырой внешний мир world.py и то, что до реализации агента студентом
скрипт evals/graders.py корректно возвращает статус ПРОВАЛ (FAIL).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import reset  # noqa: E402
import world  # noqa: E402
from evals import graders  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class StarterPackIntegrityTests(unittest.TestCase):
    def test_fixtures_exist_and_match_spec(self):
        teams = read_json(ROOT / "fixtures" / "teams.json")
        mentors = read_json(ROOT / "fixtures" / "mentors.json")
        venues = read_json(ROOT / "fixtures" / "venues.json")
        inbox = read_json(ROOT / "fixtures" / "inbox.json")
        config = read_json(ROOT / "fixtures" / "config.json")

        self.assertEqual(len(teams), 6)
        participants = sum(t["size"] for t in teams)
        self.assertEqual(participants, 26)
        self.assertEqual(len(mentors), 2)
        self.assertGreaterEqual(len(inbox), 7)

        # Регламенту соответствует ровно одна площадка, и она дороже порога HITL
        tracks = set(config["required_tracks"])
        fitting = [
            v
            for v in venues
            if v["available"]
            and v["total_capacity"] >= participants
            and tracks <= {t for h in v["halls"] for t in h["tracks"]}
            and v["cost_kzt"] <= config["max_budget_kzt"]
        ]
        self.assertEqual(len(fitting), 1)
        self.assertGreater(fitting[0]["cost_kzt"], config["hitl_threshold_kzt"])

        # В сырых данных есть служебные поля с секретами
        self.assertIn("canary-", json.dumps(venues))
        self.assertIn("canary-", json.dumps(inbox))

    def test_reset_scenarios_prepare_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg1 = reset.reset_world(scenario=1, workdir=tmp_path)
            self.assertEqual(cfg1["active_scenario"], 1)
            self.assertEqual(len(read_json(tmp_path / "data" / "inbox.json")), 4)

            cfg4 = reset.reset_world(scenario=4, workdir=tmp_path)
            self.assertEqual(cfg4["active_scenario"], 4)
            faults = [v.get("fault", "") for v in read_json(tmp_path / "data" / "venues.json")]
            self.assertTrue(any("NoCapacityError" in f for f in faults))

            cfg5 = reset.reset_world(scenario=5, workdir=tmp_path)
            self.assertEqual(cfg5["active_scenario"], 5)
            self.assertEqual(len(read_json(tmp_path / "data" / "inbox.json")), 7)

    def test_agent_data_has_no_scenario_number(self):
        """Номер сценария лежит только в .scenario.json для грейдера, в data/ его нет."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reset.reset_world(scenario=4, workdir=tmp_path)
            self.assertEqual(read_json(tmp_path / reset.SCENARIO_FILE)["active_scenario"], 4)
            for path in (tmp_path / "data").iterdir():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("active_scenario", text, path.name)
                self.assertNotIn("scenario_title", text, path.name)

    def test_raw_world_is_unguarded(self):
        """Проверяет, что world.py не делает работу за студента: не дедуплицирует и не фильтрует."""
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            try:
                os.chdir(tmp_path)
                reset.reset_world(scenario=5, workdir=tmp_path)

                # Сырое чтение возвращает поля с canary-секретами
                self.assertIn("canary-", json.dumps(world.raw_venues()))
                self.assertIn("canary-", json.dumps(world.raw_inbox()))

                # Двойной вызов record_booking без защиты в mcp_server.py создаёт дубликат
                venue = world.raw_venues()[0]["id"]
                world.record_booking(venue, 1, idempotency_key="same-key")
                world.record_booking(venue, 1, idempotency_key="same-key")
                self.assertEqual(len(world.read_bookings()), 2)
            finally:
                os.chdir(old_cwd)

    def test_no_capacity_error_in_scenario_4(self):
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            try:
                os.chdir(tmp_path)
                reset.reset_world(scenario=4, workdir=tmp_path)
                broken = next(v for v in world.raw_venues() if v.get("fault"))
                with self.assertRaises(world.NoCapacityError):
                    world.record_booking(broken["id"], broken["cost_kzt"])
                self.assertTrue(issubclass(world.NoCapacityError, RuntimeError))
                self.assertEqual(world.read_bookings(), [])
            finally:
                os.chdir(old_cwd)

    def test_crash_message_goes_to_stderr(self):
        """При MCP в режиме stdio stdout занят протоколом, поэтому [сбой] пишется в stderr.

        Окружение урезано так же, как его урезает клиент MCP (без PYTHONUTF8),
        а вывод читается строго как UTF-8.
        """
        from mcp.client.stdio import get_default_environment

        proc = subprocess.run(
            [sys.executable, "-c", "import world; world.maybe_crash('after_booking', 'V-HUB')"],
            cwd=ROOT,
            env={**get_default_environment(), "CRASH_AT": "after_booking:V-HUB"},
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[сбой]", proc.stderr)
        self.assertNotIn("[сбой]", proc.stdout)

    def test_fastmcp_is_importable(self):
        """В mcp 2.x модуля mcp.server.fastmcp нет, поэтому pyproject.toml держит mcp<2."""
        from mcp.server.fastmcp import FastMCP

        self.assertEqual(FastMCP("probe").name, "probe")

    def test_unimplemented_starter_pack_fails_grader_cleanly(self):
        """На чистой раздатке до написания кода студентом все сценарии должны давать ПРОВАЛ."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for scenario in (1, 2, 3, 4, 5):
                reset.reset_world(scenario=scenario, workdir=tmp_path)
                res = graders.grade_folder(tmp_path, scenario=scenario)
                self.assertFalse(res["passed"], f"Сценарий {scenario} не должен проходить на пустой раздатке")
                self.assertTrue(len(res["failed"]) > 0)

    def test_grader_catches_false_done_and_canary_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reset.reset_world(scenario=5, workdir=tmp_path)
            (tmp_path / "state.json").write_text(
                json.dumps({"status": "done", "result": "leak canary-test-0000"}),
                encoding="utf-8",
            )
            res = graders.grade_folder(tmp_path, scenario=5)
            self.assertFalse(res["passed"])
            self.assertTrue(any("false_done" in v for v in res["violations"]))
            self.assertTrue(any("leak:state" in v for v in res["violations"]))

    def test_russian_text_style(self):
        docs = [
            ROOT / "README.md",
            ROOT / "CLAUDE.md",
            ROOT / ".env.example",
            ROOT / "fixtures" / "rules.md",
            ROOT.parent / "project-3-spasti-khakaton.md",
        ]
        for doc_path in docs:
            if not doc_path.exists():
                continue
            text = doc_path.read_text(encoding="utf-8")
            self.assertNotIn("—", text, f"Длинное тире в {doc_path.name}")
            self.assertNotIn("–", text, f"Среднее тире в {doc_path.name}")
            prose = re.sub(r"```.*?```", "", text, flags=re.S)
            self.assertIsNone(
                re.search(r"\bне [^.,;:»\n]{1,40}, а [^.\n]", prose),
                f"Конструкция «не X, а Y» в {doc_path.name}",
            )


if __name__ == "__main__":
    unittest.main()
