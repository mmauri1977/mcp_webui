import asyncio
import logging
import sys
import threading
import streamlit as st
from main import Server, LLMClient, Configuration, ChatSession, Tool
from typing import List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# Set Windows asyncio event loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def chat():
    """Initialize and run the Streamlit chat application."""
    logging.info(f"Running chat in thread: {threading.current_thread().name}")
    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "chat_session" not in st.session_state:
        try:
            config = Configuration()
            server_config = config.load_config("servers_config.json")
            servers = [Server(name, srv_config) for name, srv_config in server_config["mcpServers"].items()]
            llm_client = LLMClient(config.llm_api_key)
            chat_session = ChatSession(servers, llm_client)
            
            # Initialize servers with timeout
            for server in servers:
                try:
                    await asyncio.wait_for(server.initialize(), timeout=30.0)
                except asyncio.TimeoutError:
                    logging.error(f"Timeout initializing server {server.name}")
                    st.error(f"Server {server.name} failed to initialize: Timeout")
                    await chat_session.cleanup_servers()
                    raise
                except asyncio.CancelledError as e:
                    logging.error(f"Server {server.name} initialization cancelled: {e}")
                    await chat_session.cleanup_servers()
                    raise
                except Exception as e:
                    logging.error(f"Failed to initialize server {server.name}: {e}")
                    st.error(f"Server {server.name} failed to initialize: {str(e)}")
                    await chat_session.cleanup_servers()
                    raise
            
            # Cache tools
            all_tools = []
            for server in servers:
                try:
                    tools = await asyncio.wait_for(server.list_tools(), timeout=10.0)
                    all_tools.extend(tools)
                except asyncio.TimeoutError:
                    logging.error(f"Timeout listing tools for {server.name}")
                    st.error(f"Failed to list tools for {server.name}: Timeout")
                    await chat_session.cleanup_servers()
                    raise
                except asyncio.CancelledError as e:
                    logging.error(f"Tool listing for {server.name} cancelled: {e}")
                    await chat_session.cleanup_servers()
                    raise
                except Exception as e:
                    logging.error(f"Failed to list tools for {server.name}: {e}")
                    st.error(f"Failed to list tools for {server.name}: {str(e)}")
                    await chat_session.cleanup_servers()
                    raise
            chat_session.tools_cache = all_tools
            
            # Set system message
            tools_description = "\n".join([tool.format_for_llm() for tool in all_tools])
            system_message = (
                "You are a helpful assistant with real access to these tools:\n\n"
                f"{tools_description}\n"
                "Choose the appropriate tool based on the user's question and execute the tool to perform the action. "
                "If no tool is needed, reply directly.\n\n"
                "If a tool does not work, explain the error to the user and suggest a different tool.\n\n"
                "IMPORTANT: When you need to use a tool, you must respond with "
                "the exact JSON object format below, nothing else:\n"
                "{\n"
                '    "tool": "tool-name",\ HAP\n'
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
            st.session_state.messages.append({
                "role": "system",
                "content": system_message
            })
            st.session_state.chat_session = chat_session
        except Exception as e:
            st.error(f"Failed to initialize chat session: {str(e)}")
            logging.error(f"Initialization error: {str(e)}")
            await chat_session.cleanup_servers()
            return

    # Streamlit UI
    st.title("MCP Tool-Executing Chatbot")
    st.write("Interact with the assistant to execute MongoDB, SQLite, or Weather queries.")

    # Sidebar with tool list and test buttons
    st.sidebar.title("Available Tools")
    if st.session_state.chat_session.tools_cache:
        for tool in st.session_state.chat_session.tools_cache:
            st.sidebar.markdown(f"**{tool.name}**: {tool.description}")
    else:
        st.sidebar.markdown("No tools available. Check server initialization.")

    if st.sidebar.button("Test MCP Server"):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8080/tools")
                st.sidebar.success(f"MCP Server Tools: {response.json()}")
        except Exception as e:
            st.sidebar.error(f"MCP Server Test Failed: {str(e)}")

    if st.sidebar.button("Cleanup Servers"):
        if "chat_session" in st.session_state:
            await st.session_state.chat_session.cleanup_servers()
            st.sidebar.success("Servers cleaned up successfully")
        else:
            st.sidebar.error("No active chat session to clean up")

    # Display chat history
    for message in st.session_state.messages:
        if message["role"] != "system":
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Handle user input
    if user_input := st.chat_input("Type your message (e.g., 'Query MongoDB for users')..."):
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.spinner("Processing..."):
            try:
                chat_session = st.session_state.chat_session
                # Prepare tools for LLM
                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema
                        }
                    }
                    for tool in chat_session.tools_cache
                ]
                # Get LLM response
                llm_response = chat_session.llm_client.get_response(
                    st.session_state.messages,
                    tools=tools
                )
                logging.info(f"LLM response: {llm_response}")

                if "content" in llm_response and "rate limit" in llm_response["content"].lower():
                    st.error("Rate limit reached. Please wait a moment and try again.")
                    await chat_session.cleanup_servers()
                    return

                # Process response (handles content or tool_calls)
                result = await chat_session.process_llm_response(llm_response)

                if result != llm_response.get("content", ""):
                    st.session_state.messages.append({"role": "assistant", "content": llm_response.get("content", "")})
                    st.session_state.messages.append({"role": "system", "content": result})
                    final_response = chat_session.llm_client.get_response(
                        st.session_state.messages,
                        tools=tools
                    )
                    st.session_state.messages.append({"role": "assistant", "content": final_response.get("content", "")})
                else:
                    st.session_state.messages.append({"role": "assistant", "content": result})
                    final_response = {"content": result}

                with st.chat_message("assistant"):
                    st.markdown(final_response.get("content", "No response content"))

            except asyncio.CancelledError as e:
                logging.error(f"Query processing cancelled: {e}")
                st.error("Operation was cancelled. Please try again.")
                await chat_session.cleanup_servers()
            except Exception as e:
                error_msg = f"Error processing response: {str(e)}"
                logging.error(error_msg)
                with st.chat_message("assistant"):
                    st.error(error_msg)
                await chat_session.cleanup_servers()

        st.rerun()

if __name__ == "__main__":
    try:
        asyncio.run(chat())
    except asyncio.CancelledError as e:
        logging.error(f"Main chat loop cancelled: {e}")
        st.error("Application was cancelled unexpectedly. Please restart.")