import unittest
from unittest.mock import patch, mock_open
import server

class TestServer(unittest.TestCase):
    def test_get_knowledge_base_file_not_found(self):
        with patch('builtins.open', side_effect=FileNotFoundError()):
            result = server.get_knowledge_base()
            self.assertEqual(result, "Error: KB File not found")

    def test_get_knowledge_base_invalid_json(self):
        m = mock_open(read_data='invalid json')
        with patch('builtins.open', m), patch('json.load', side_effect=ValueError()):
            result = server.get_knowledge_base()
            self.assertEqual(result, "Invalid JSON file")

    @patch('server.requests.get')
    def test_get_weather_success(self, mock_get):
        # Mock geocoding API response
        mock_get.side_effect = [
            unittest.mock.Mock(status_code=200, json=lambda: {"results": [{"latitude": 10, "longitude": 20}]}),
            unittest.mock.Mock(status_code=200, json=lambda: {"current_weather": {"temperature": 25.5}})
        ]
        result = server.get_weather("TestCity")
        self.assertIn("The current temperature in TestCity is 25.5°C.", result)

    @patch('server.requests.get')
    def test_get_weather_city_not_found(self, mock_get):
        mock_get.return_value = unittest.mock.Mock(status_code=200, json=lambda: {"results": []})
        result = server.get_weather("UnknownCity")
        self.assertIn("Error fetching location data", result)

    @patch('server.requests.get')
    def test_get_weather_api_error(self, mock_get):
        mock_get.return_value = unittest.mock.Mock(status_code=404)
        result = server.get_weather("TestCity")
        self.assertIn("Error fetching location data", result)

    @patch('server.requests.get')
    def test_get_weather_weather_api_error(self, mock_get):
        # Mock geocoding API response
        mock_get.side_effect = [
            unittest.mock.Mock(status_code=200, json=lambda: {"results": [{"latitude": 10, "longitude": 20}]}),
            unittest.mock.Mock(status_code=500)
        ]
        result = server.get_weather("TestCity")
        self.assertIn("Error fetching weather data: 500", result)

    @patch('server.requests.get')
    def test_fly_information_no_data(self, mock_get):
        mock_get.return_value = unittest.mock.Mock(status_code=200, json=lambda: {"data": []})
        result = server.fly_information("UA100")
        self.assertIn("No information found for flight UA100.", result)

    @patch('server.requests.get')
    def test_fly_information_success(self, mock_get):
        mock_get.return_value = unittest.mock.Mock(status_code=200, json=lambda: {
            "data": [{
                "airline": {"name": "TestAir"},
                "departure": {"airport": "A"},
                "arrival": {"airport": "B"},
                "departure": {"scheduled": "2025-05-20T10:00:00"},
                "arrival": {"scheduled": "2025-05-20T12:00:00"},
                "flight_status": "active"
            }]
        })
        result = server.fly_information("UA100")
        self.assertIn("Flight UA100 operated by TestAir", result)

if __name__ == "__main__":
    unittest.main()
