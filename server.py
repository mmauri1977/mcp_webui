import os
import requests
import json
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Create an MCP Server
mcp = FastMCP(
    name="Knowledge Base",
    host="0.0.0.0",
    port=8050
)

load_dotenv(".env")

@mcp.tool()
def get_knowledge_base() -> str:
    """
    Retrieve the entire knowledge base of the company as a formatted string
    :return: A formatted string containing all Q&A pairs
    """
    try:
        kb_path = os.path.join(os.path.dirname(__file__), "data", "kb.json")
        with open(kb_path, "r") as f:
            kb_data = json.load(f)
        kb_text = "Here is the retrieved knowledge base for the user's company:\n\n"

        if isinstance(kb_data, list):
            for i, item in enumerate(kb_data, 1):
                if isinstance(item, dict):
                    question = item.get("question", "Unknown question")
                    answer = item.get("answer", "Unknown answer")
                else:
                    question = f"Item {i}"
                    answer = str(item)

                kb_text += f"Q{i}: {question}\n"
                kb_text += f"A{i}: {answer}\n"
        else:
            kb_text += f"Knowledge base content: {json.dumps(kb_data, indent=2)}\n\n"

        return kb_text
    except FileNotFoundError:
        return "Error: KB File not found"
    except json.JSONDecodeError:
        return "Invalid JSON file"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def fly_information(flight_iata: str) -> str:
    """
    Retrieve flight information using the Aviationstack API.
    :param flight_iata: The IATA flight number (e.g., 'UA100').
    :return: A formatted string with flight details.
    """
    #api_key = os.getenv("AVIATIONSTACK_API_KEY")
    #if not api_key:
    #    return "Error: AVIATIONSTACK_API_KEY environment variable not set."

    url = "http://api.aviationstack.com/v1/flights"
    params = {
        #"access_key": api_key,
        "access_key": "3b7de7457c004c9f4ce76ee1511a6621",
        "flight_iata": flight_iata
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if not data["data"]:
            print("No flight information")
            return f"No information found for flight {flight_iata}."

        print(f"Flight information found: {json.dumps(data, indent=2)}")
        flight = data["data"][0]
        airline = flight["airline"]["name"]
        departure_airport = flight["departure"]["airport"]
        arrival_airport = flight["arrival"]["airport"]
        departure_time = flight["departure"]["scheduled"]
        arrival_time = flight["arrival"]["scheduled"]
        flight_status = flight["flight_status"]

        return (
            f"Flight {flight_iata} operated by {airline}:\n"
            f"Status: {flight_status}\n"
            f"Departure: {departure_airport} at {departure_time}\n"
            f"Arrival: {arrival_airport} at {arrival_time}"
        )

    except requests.RequestException as e:
        return f"Error retrieving flight information: {e}"

@mcp.tool()
def get_weather(city: str) -> str | None:
    """
    Returns the weather information for a city.
    :param city:
    :return:
    """
    #return f"The current weather in {city} is sunny and 25°C."
    api_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=10&language=en&format=json"
    response = requests.get(api_url)

    if response.status_code == 200:
        data = response.json()
        if "results" in data and len(data["results"]) > 0:
            city_info = data["results"][0]
            lat = city_info["latitude"]
            lon = city_info["longitude"]

            weather_api_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m&current_weather=true"
            weather_response = requests.get(weather_api_url)

            if weather_response.status_code == 200:
                weather_data = weather_response.json()
                temp = weather_data.get("current_weather", {}).get("temperature")
                return f"The current temperature in {city} is {temp}°C."
            else:
                return f"Error fetching weather data: {weather_response.status_code}"
    return f"Error fetching location data: {response.status_code}"


# Run the server
if __name__ == "__main__":
    mcp.run(transport="stdio")