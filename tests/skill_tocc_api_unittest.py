import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "test_skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import search_experts  # noqa: E402
import search_resources  # noqa: E402
from tocc_api import ToccApiError  # noqa: E402


class SkillToccApiTests(unittest.TestCase):
    def tearDown(self):
        search_experts.ToccApiClient = self._original_expert_client
        search_resources.ToccApiClient = self._original_resource_client

    def setUp(self):
        self._original_expert_client = search_experts.ToccApiClient
        self._original_resource_client = search_resources.ToccApiClient

    def test_search_experts_prefers_api_records(self):
        class FakeClient:
            def get_experts(self):
                return [
                    {
                        "id": "expert-1",
                        "name": "张三",
                        "specialtyField": "交通事故应急处置",
                        "duties": "道路运输安全评估",
                        "professionalTitle": "高级工程师",
                        "workUnit": "广西交通单位",
                        "major": "交通安全",
                        "phone": "13800000000",
                        "address": "南宁市",
                        "longitude": "108.32",
                        "latitude": "22.84",
                    }
                ]

        search_experts.ToccApiClient = FakeClient

        result = search_experts.search(
            keywords=["交通事故"],
            incident_type="交通事故",
            lng=108.32,
            lat=22.84,
            max_results=5,
        )

        self.assertEqual(result["data_source"], "tocc_api")
        self.assertEqual(result["experts"][0]["name"], "张三")
        self.assertEqual(result["experts"][0]["phone"], "13800000000")

    def test_search_resources_prefers_api_warehouses_and_local_teams(self):
        class FakeClient:
            def get_all_warehouses(self):
                return [
                    {
                        "id": "warehouse-1",
                        "warehouseName": "南宁应急物资库",
                        "belongOrgName": "广西交通部门",
                        "address": "南宁市青秀区",
                        "principal": "李四",
                        "contactPhone": "13900000000",
                        "longitude": "108.32",
                        "latitude": "22.84",
                        "materials": [
                            {
                                "id": "material-1",
                                "materialName": "反光锥",
                                "quantity": 20,
                                "unit": "个",
                            }
                        ],
                    }
                ]

        search_resources.ToccApiClient = FakeClient

        result = search_resources.search(
            lng=108.32,
            lat=22.84,
            radius_km=5,
            max_results=5,
        )

        self.assertEqual(result["data_freshness"]["warehouse_data_source"], "tocc_api")
        self.assertEqual(result["data_freshness"]["team_data_source"], "local")
        self.assertEqual(result["warehouses"][0]["name"], "南宁应急物资库")
        self.assertEqual(result["warehouses"][0]["materials_top"][0]["name"], "反光锥")
        self.assertIn("警示防护设备", result["warehouses"][0]["categories_zh"])

    def test_search_resources_falls_back_when_api_unavailable(self):
        class FakeClient:
            def get_all_warehouses(self):
                raise ToccApiError("unavailable")

        search_resources.ToccApiClient = FakeClient

        result = search_resources.search(
            lng=108.32,
            lat=22.84,
            radius_km=5,
            max_results=5,
        )

        self.assertEqual(result["data_freshness"]["warehouse_data_source"], "local_fallback")


if __name__ == "__main__":
    unittest.main()
