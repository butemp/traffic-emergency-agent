import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

openai_stub = types.ModuleType("openai")
openai_stub.OpenAI = object
sys.modules.setdefault("openai", openai_stub)

from src.resource_dispatch.engine import ResourceDispatchEngine
from src.tocc_api import ToccApiClient, infer_material_category, map_expert_record, map_warehouse_record
from src.tools.expert_tools import SearchExperts


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeToccClient:
    def __init__(self, experts=None, warehouses=None):
        self.experts = experts or []
        self.warehouses = warehouses or []

    def get_experts(self, **filters):
        return self.experts

    def get_all_warehouses(self, page_size=100, **filters):
        return self.warehouses


class ToccApiTest(unittest.TestCase):
    def test_get_all_warehouses_paginates_until_total(self):
        payloads = [
            {
                "code": 200,
                "total": 3,
                "rows": [{"id": "w1"}, {"id": "w2"}],
            },
            {
                "code": 200,
                "total": 3,
                "rows": [{"id": "w3"}],
            },
        ]

        with patch("src.tocc_api.requests.get", side_effect=[FakeResponse(item) for item in payloads]) as mocked:
            client = ToccApiClient(base_url="https://example.test", api_key="key", timeout=1)
            rows = client.get_all_warehouses(page_size=2)

        self.assertEqual([row["id"] for row in rows], ["w1", "w2", "w3"])
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(mocked.call_args_list[0].kwargs["params"]["pageNum"], 1)
        self.assertEqual(mocked.call_args_list[1].kwargs["params"]["pageNum"], 2)

    def test_maps_expert_record_to_internal_fields(self):
        mapped = map_expert_record(
            {
                "id": "e1",
                "name": "张三",
                "specialtyField": "桥梁安全",
                "professionalTitle": "高级工程师",
                "workUnit": "广西交通研究院",
                "phone": "13800000000",
                "longitude": "108.32",
                "latitude": "22.82",
            }
        )

        self.assertEqual(mapped["specialty_field"], "桥梁安全")
        self.assertEqual(mapped["professional_title"], "高级工程师")
        self.assertEqual(mapped["work_unit"], "广西交通研究院")
        self.assertEqual(mapped["longitude"], 108.32)
        self.assertEqual(mapped["data_source"], "tocc_api")

    def test_maps_warehouse_materials_and_categories(self):
        mapped = map_warehouse_record(
            {
                "id": "w1",
                "warehouseName": "南宁应急仓库",
                "belongOrgName": "广西高速",
                "address": "南宁市青秀区",
                "principal": "李四",
                "contactPhone": "13900000000",
                "longitude": "108.33",
                "latitude": "22.81",
                "materials": [
                    {"id": "m1", "materialName": "反光锥", "quantity": 20, "unit": "个"},
                    {"id": "m2", "materialName": "灭火器", "quantity": 10, "unit": "个"},
                ],
                "equipments": [
                    {"id": "eq1", "equipmentName": "发电机", "quantity": 1, "unit": "台"},
                ],
            }
        )

        self.assertEqual(mapped["warehouse_name"], "南宁应急仓库")
        self.assertEqual(mapped["longitude"], 108.33)
        self.assertIn("WARNING", mapped["categories"])
        self.assertIn("FIRE", mapped["categories"])
        self.assertIn("TOOL", mapped["categories"])
        self.assertEqual(mapped["materials_by_category"]["FIRE"][0]["name"], "灭火器")

    def test_expert_tool_uses_api_records_without_local_file(self):
        tool = SearchExperts(
            client=FakeToccClient(
                experts=[
                    {
                        "id": "e1",
                        "name": "王五",
                        "specialtyField": "交通安全",
                        "professionalTitle": "高级工程师",
                        "workUnit": "广西交通研究院",
                        "phone": "13700000000",
                    }
                ]
            )
        )

        result = json.loads(tool.execute(keywords=["交通安全"], incident_type="交通事故"))

        self.assertEqual(result["data_source"], "tocc_api")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["experts"][0]["name"], "王五")

    def test_resource_engine_uses_api_warehouses_and_local_teams(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            team_path = Path(tmpdir) / "teams.json"
            team_path.write_text("[]", encoding="utf-8")

            engine = ResourceDispatchEngine(
                team_index_path=str(team_path),
                client=FakeToccClient(
                    warehouses=[
                        {
                            "id": "w1",
                            "warehouseName": "南宁应急仓库",
                            "address": "南宁市青秀区",
                            "principal": "李四",
                            "contactPhone": "13900000000",
                            "longitude": 108.33,
                            "latitude": 22.81,
                            "materials": [
                                {"id": "m1", "materialName": "反光锥", "quantity": 20, "unit": "个"},
                                {"id": "m2", "materialName": "灭火器", "quantity": 10, "unit": "个"},
                            ],
                        }
                    ]
                ),
            )

            result = engine.search_resources(
                longitude=108.3301,
                latitude=22.8101,
                required_categories=["WARNING", "FIRE"],
                radius_km=5,
            )

        self.assertEqual(result["data_freshness"]["warehouse_data_source"], "tocc_api")
        self.assertEqual(len(result["candidates"]["warehouses"]), 1)
        self.assertEqual(result["coverage"]["covered_categories"], ["FIRE", "WARNING"])

    def test_material_category_fallbacks_to_other(self):
        self.assertEqual(infer_material_category("未知专用设备"), "OTHER")


if __name__ == "__main__":
    unittest.main()
