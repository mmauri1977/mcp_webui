import asyncio
import json
import logging
import os
import shutil
import time
from contextlib import AsyncExitStack
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class Configuration:
    """Manages configuration and environment variables for the MCP client."""

    def __init__(self) -> None:
        """Initialize configuration with environment variables."""
        self.load_env()
        self.api_key = "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"
        #os.getenv("LLM_API_KEY")

    @staticmethod
    def load_env() -> None:
        """Load environment variables from .env file."""
        load_dotenv()

    @staticmethod
    def load_config(file_path: str) -> dict[str, Any]:
        """Load server configuration from JSON file.

        Args:
            file_path: Path to the JSON configuration file.

        Returns:
            Dict containing server configuration.

        Raises:
            FileNotFoundError: If configuration file doesn't exist.
            JSONDecodeError: If configuration file is invalid JSON.
        """
        with open(file_path, "r") as f:
            return json.load(f)

    @property
    def llm_api_key(self) -> str:
        """Get the LLM API key.

        Returns:
            The API key as a string.

        Raises:
            ValueError: If the API key is not found in environment variables.
        """
        if not self.api_key:
            raise ValueError("LLM_API_KEY not found in environment variables")
        return self.api_key


class Server:
    """Manages MCP server connections and tool execution."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name: str = name
        self.config: dict[str, Any] = config
        self.stdio_context: Any | None = None
        self.session: ClientSession | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack: AsyncExitStack = AsyncExitStack()

    async def initialize(self) -> None:
        """Initialize the server connection."""
        command = (
            shutil.which("npx")
            if self.config["command"] == "npx"
            else self.config["command"]
        )
        if command is None:
            raise ValueError("The command must be a valid string and cannot be None.")

        server_params = StdioServerParameters(
            command=command,
            args=self.config["args"],
            env={**os.environ, **self.config["env"]}
            if self.config.get("env")
            else None,
        )
        try:
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self.session = session
        except Exception as e:
            logging.error(f"Error initializing server {self.name}: {e}")
            await self.cleanup()
            raise

    async def list_tools(self) -> list[Any]:
        """List available tools from the server.

        Returns:
            A list of available tools.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        tools_response = await self.session.list_tools()
        tools = []

        for item in tools_response:
            if isinstance(item, tuple) and item[0] == "tools":
                tools.extend(
                    Tool(tool.name, tool.description, tool.inputSchema)
                    for tool in item[1]
                )

        return tools

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 2,
        delay: float = 1.0,
    ) -> Any:
        """Execute a tool with retry mechanism.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            Tool execution result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        attempt = 0
        while attempt < retries:
            try:
                logging.info(f"Executing {tool_name}...")
                result = await self.session.call_tool(tool_name, arguments)

                return result

            except Exception as e:
                attempt += 1
                logging.warning(
                    f"Error executing tool: {e}. Attempt {attempt} of {retries}."
                )
                if attempt < retries:
                    logging.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logging.error("Max retries reached. Failing.")
                    raise

    async def cleanup(self) -> None:
        """Clean up server resources."""
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
                self.stdio_context = None
            except Exception as e:
                logging.error(f"Error during cleanup of server {self.name}: {e}")


class Tool:
    """Represents a tool with its properties and formatting."""

    def __init__(
        self, name: str, description: str, input_schema: dict[str, Any]
    ) -> None:
        self.name: str = name
        self.description: str = description
        self.input_schema: dict[str, Any] = input_schema

    def to_api_dict(self) -> dict:
        """Convert the tool to a dictionary format for the API."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema
            }
        }        

    def format_for_llm(self) -> str:
        """Format tool information for LLM.

        Returns:
            A formatted string describing the tool.
        """
        args_desc = []
        if "properties" in self.input_schema:
            for param_name, param_info in self.input_schema["properties"].items():
                arg_desc = (
                    f"- {param_name}: {param_info.get('description', 'No description')}"
                )
                if param_name in self.input_schema.get("required", []):
                    arg_desc += " (required)"
                args_desc.append(arg_desc)

        return f"""

Tool: {self.name}
Description: {self.description}
Arguments:
{chr(10).join(args_desc)}
"""


class LLMClient:
    """Manages communication with the LLM provider."""

    def __init__(self, api_key: str, servers: list[Server]) -> None:
        self.api_key: str = api_key
        self.servers: list[Server] = servers
        self.all_tools: list[dict] = []  # Tools will be populated later
        self.tools_description: str = ""

    async def initialize_tools(self) -> None:
        """Asynchronously fetch and store tools from all servers."""
        for server in self.servers:
            try:
                tools = await server.list_tools()
                # Convert Tool objects to dictionaries
                self.all_tools.extend([tool.to_api_dict() for tool in tools])
            except Exception as e:
                logging.error(f"Failed to fetch tools from server {server.name}: {e}")

    def get_response(self, messages: list[dict[str, str]], tools: list[dict] = None) -> str:

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
           "Content-Type": "application/json",
           "Authorization": f"Bearer {self.api_key}",
        }
        # Base payload fields that always go out
        payload = {
            "messages": messages,
            "model": "llama-3.1-8b-instant",
            "temperature": 0.7,
            "max_tokens": 4096,
            "top_p": 1,
            "stream": False,
        }

        # Conditionally inject tools only if there are any
        if self.all_tools:
            payload["tools"] = self.all_tools
            payload["tool_choice"] = "auto"

        # (Optional) log it to debug
        logging.debug("Sending payload: %s", json.dumps(payload, indent=2))
                
        max_retries = 5
        backoff = 2  # start at 2 seconds

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(url, headers=headers, json=payload)
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("retry-after", backoff))
                        logging.warning(f"Rate limit hit. Retrying after {retry_after}s...")
                        time.sleep(retry_after)
                        backoff *= 2
                        continue
                    try:
                        response.raise_for_status()
                        data = response.json()
                        logging.info("LLM response JSON: %s", data)
                        choice = data["choices"][0]["message"]

                        # 1) If the model invoked a tool:
                        if "tool_calls" in choice and choice["tool_calls"]:
                            call = choice["tool_calls"][0]["function"]
                            name = call["name"]
                            # `arguments` is a JSON‐encoded string; parse it
                            args = json.loads(call["arguments"])
                            # Return exactly the JSON object to drive your tool executor
                            return json.dumps({"tool": name, "arguments": args})

                        # 2) Otherwise return the normal content:
                        content = choice.get("content")
                        if content is not None:
                            return content

                        # 3) If neither is present, raise for visibility
                        raise RuntimeError(f"Unexpected LLM response shape: {data}")
                    except httpx.HTTPStatusError:
                        logging.error("LLM error response body: %s", response.text)
                        raise

            except httpx.HTTPStatusError as e:
                logging.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise

            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                raise

        raise RuntimeError("Max retries exceeded while calling LLM")


class ChatSession:
    """Orchestrates the interaction between user, LLM, and tools."""

    def __init__(self, servers: list[Server], llm_client: LLMClient) -> None:
        self.servers: list[Server] = servers
        self.llm_client: LLMClient = llm_client

    async def cleanup_servers(self) -> None:
        """Clean up all servers properly."""
        cleanup_tasks = [
            asyncio.create_task(server.cleanup()) for server in self.servers
        ]
        if cleanup_tasks:
            try:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            except Exception as e:
                logging.warning(f"Warning during final cleanup: {e}")

    async def process_llm_response(self, llm_response: str) -> str:
        """Process the LLM response and execute tools if needed.

        Args:
            llm_response: The response from the LLM.

        Returns:
            The result of tool execution or the original response.
        """
        import json

        try:
            tool_call = json.loads(llm_response)
            if "tool" in tool_call and "arguments" in tool_call:
                name = tool_call["tool"]
                raw_args = tool_call["arguments"]

                # Find the matching Tool schema
                for server in self.servers:
                    tools = await server.list_tools()
                    for tool in tools:
                        if tool.name == name:
                            schema = tool.input_schema
                            break
                    else:
                        continue
                    break
                else:
                    return f"No server found with tool: {name}"

                # Sanitize each argument according to its schema type
                props = schema.get("properties", {})
                for arg_name, arg_value in list(raw_args.items()):
                    expected = props.get(arg_name, {}).get("type")
                    # If schema says object or array, but we got a str, try to parse
                    if expected in ("object", "array") and isinstance(arg_value, str):
                        try:
                            raw_args[arg_name] = json.loads(arg_value)
                        except json.JSONDecodeError:
                            # Fallback: empty object or list
                            raw_args[arg_name] = {} if expected == "object" else []

                # Now execute with corrected args
                result = await server.execute_tool(name, raw_args)
                return f"Tool execution result: {result}"
        except json.JSONDecodeError:
            return llm_response

    async def start(self) -> None:
        """Main chat session handler."""
        try:
            for server in self.servers:
                try:
                    await server.initialize()
                except Exception as e:
                    logging.error(f"Failed to initialize server: {e}")
                    await self.cleanup_servers()
                    return

            all_tools = []
            for server in self.servers:
                tools = await server.list_tools()
                all_tools.extend(tools)

            tools_description = "\n".join([tool.format_for_llm() for tool in all_tools])

            system_message = (
                "You are a helpful assistant with real access to these tools:\n\n"
                f"{tools_description}\n"
                "Choose the appropriate tool based on the user's question and execute the tool to perform the action. "
                "If no tool is needed, reply directly.\n\n"
                "if a tool does not work, explain the error to the user and suggest a different tool.\n\n"
                "IMPORTANT: When you need to use a tool, you must ONLY respond with "
                "the exact JSON object format below, nothing else:\n"
                "{\n"
                '    "tool": "tool-name",\n'
                '    "arguments": {\n'
                '        "argument-name": "value"\n'
                "    }\n"
                "}\n\n"
                "After receiving a tool's response:\n"
                "1. Transform the raw data into a natural, conversational response\n"
                "2. Keep responses concise but informative\n"
                "3. Focus on the most relevant information\n"
                "4. Use appropriate context from the user's question\n"
                "5. Avoid simply repeating the raw data\n\n"
                "Please use only the tools that are explicitly defined above."
            )

            messages = [{"role": "system", "content": system_message}]

            while True:
                try:
                    user_input = input("You: ").strip().lower()
                    if user_input in ["quit", "exit"]:
                        logging.info("\nExiting...")
                        break

                    messages.append({"role": "user", "content": user_input})

                    llm_response = self.llm_client.get_response(messages, all_tools)
                    logging.info("\nAssistant: %s", llm_response)

                    result = await self.process_llm_response(llm_response)

                    if result != llm_response:
                        messages.append({"role": "assistant", "content": llm_response})
                        messages.append({"role": "system", "content": result})

                        final_response = self.llm_client.get_response(messages, all_tools)
                        logging.info("\nFinal response: %s", final_response)
                        messages.append(
                            {"role": "assistant", "content": final_response}
                        )
                    else:
                        messages.append({"role": "assistant", "content": llm_response})

                except KeyboardInterrupt:
                    logging.info("\nExiting...")
                    break

        finally:
            await self.cleanup_servers()


async def main() -> None:
    """Initialize and run the chat session."""
    config = Configuration()
    server_config = config.load_config("servers_config.json")
    servers = [
        Server(name, srv_config)
        for name, srv_config in server_config["mcpServers"].items()
    ]
    llm_client = LLMClient(config.llm_api_key)
    chat_session = ChatSession(servers, llm_client)
    await chat_session.start()


if __name__ == "__main__":
    asyncio.run(main())
