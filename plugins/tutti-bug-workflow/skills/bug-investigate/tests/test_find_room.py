import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/find_room.py"
LOCAL_A = {"id": "ff9e2c5b-7037-4b89-87e7-d503f811be8d", "name": "Tutti-Chovy 1012 (3)", "type": "local",
           "nativeComputerId": "04dbcb99-e20d-41e7-82fa-a01e211973bc"}
LOCAL_B = {"id": "fcfbb67a-56ae-4396-8534-e4c5e7beb989", "name": "Tutti-Chovy 1011", "type": "local"}
LOCAL_C = {"id": "5f3fdc3a-bb49-4703-b673-113d416e7b17", "name": "TIBO 本地房间", "type": "local"}
CLOUD = {"id": "6e7f1410-17ba-44f7-9ce6-e0e361c0a908", "name": "任务需求&bug管理", "type": "cloud"}
CLOUD_CHOVY = {"id": "e51bdf6f-135f-4b0c-bb77-dd1465fcfd25", "name": "Chovy 1009", "type": "cloud"}


class FindRoomTest(unittest.TestCase):
    def setUp(self):
        self.rooms = Path(tempfile.mkdtemp()) / "rooms.json"
        self.rooms.write_text(json.dumps({"rooms": [CLOUD, LOCAL_A, LOCAL_B, LOCAL_C, CLOUD_CHOVY]}))

    def find(self, query, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--query", query, "--rooms-file", str(self.rooms)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_room_id_and_links_match_the_directory(self):
        self.assertEqual(self.find(CLOUD["id"])["room"], CLOUD)
        link = f"https://tutti.sh/platform/room/{LOCAL_A['id']}?surface=task-board&task=0207d5c6-243c-4c83-ac66-aeb723d2d617"
        result = self.find(link)
        self.assertEqual((result["status"], result["by"], result["room"]["id"]), ("matched", "id", LOCAL_A["id"]))
        missing = self.find("00000000-1111-2222-3333-444444444444")
        self.assertEqual((missing["status"], missing["by"]), ("not_found", "id"))

    def test_names_prefer_local_rooms_then_cloud(self):
        self.assertEqual(self.find("tibo")["room"], LOCAL_C)
        chovy = self.find("chovy")  # two local rooms match; the cloud one is not considered
        self.assertEqual((chovy["status"], chovy["candidate_count"]), ("ambiguous", 2))
        self.assertEqual(self.find("Tutti-Chovy 1011")["room"], LOCAL_B)
        self.assertEqual(self.find("bug管理")["room"], CLOUD)

    def test_unknown_name_offers_local_rooms(self):
        result = self.find("不存在的房间")
        self.assertEqual((result["status"], result["local_room_count"]), ("not_found", 3))

    def test_unreadable_directory(self):
        self.rooms.write_text("{}")
        self.find("tibo", expected=2)


if __name__ == "__main__":
    unittest.main()
