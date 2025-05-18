from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

def main():
    # Replace with your connection string
    MONGO_URI = "mongodb+srv://mcpuser:mcp1234@mcp.ndnxscx.mongodb.net/mcpdb?retryWrites=true&w=majority&appName=MCP"

    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Force connection on a request
        client.admin.command("ping")
        print("✅ Connected successfully to MongoDB Atlas!")

        # Optional: list databases or collections
        print("Databases:", client.list_database_names())
        db = client["mcpdb"]
        print("Collections:", db.list_collection_names())

    except ConnectionFailure as e:
        print("❌ Connection failed:", e)

if __name__ == "__main__":
    main()
