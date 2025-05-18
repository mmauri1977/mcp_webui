import sys
import streamlit as st
import asyncio
import json
from main import Configuration, Server, LLMClient, ChatSession

# Streamlit page must be configured first
st.set_page_config(page_title="MCP Chatbot", layout="wide")

# Ensure Windows uses ProactorEventLoop for subprocess support
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Title/header
st.title("💬 MCP Chatbot")

# 1) CACHING BACKEND INITIALIZATION
@st.cache_resource
def init_chat_backend():
    # Create a dedicated event loop for MCP work
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Load configuration and initialize servers
    config = Configuration()
    server_cfg = Configuration.load_config("servers_config.json")
    servers = [Server(name, cfg) for name, cfg in server_cfg["mcpServers"].items()]

    # Initialize each server exactly once
    for srv in servers:
        loop.run_until_complete(srv.initialize())

    # Create LLM client and chat session
    llm = LLMClient(config.llm_api_key)
    chat_session = ChatSession(servers, llm)
    return loop, servers, llm, chat_session

# 2) RETRIEVE CACHED BACKEND
loop, servers, llm_client, chat_session = init_chat_backend()

# Build the system prompt with available tools (only on first run)
if "messages" not in st.session_state:
    tools = []
    for srv in servers:
        tools.extend(loop.run_until_complete(srv.list_tools()))
    desc = "\n".join(t.format_for_llm() for t in tools)
    system_msg = (
        "You are an assistant with access to these tools:\n\n"
        f"{desc}\n\n"
        "If you need a tool, respond *only* with JSON (no extra text):\n"
        '{"tool":"<name>","arguments":{…}}\n'
        "Otherwise, answer as a helpful assistant."
    )
    st.session_state.messages = [{"role": "system", "content": system_msg}]
    st.session_state.history = []

# Display conversation history using chat message bubbles
for entry in st.session_state.history:
    if entry["role"] == "user":
        st.chat_message("user").write(entry["content"])
    else:
        st.chat_message("assistant").markdown(entry["content"])

# Chat input from user
user_text = st.chat_input("You:")
if user_text:
    # Record user message
    st.session_state.history.append({"role": "user", "content": user_text})
    st.session_state.messages.append({"role": "user", "content": user_text})

    # Get LLM response synchronously via our event loop
    try:
        llm_reply = loop.run_until_complete(
            loop.run_in_executor(None, llm_client.get_response, st.session_state.messages, None)
        )
    except Exception as e:
        st.error(f"LLM error: {e}")
        st.stop()

    # Attempt to parse JSON tool call
    try:
        payload = json.loads(llm_reply)
    except json.JSONDecodeError:
        payload = None

    if payload and "tool" in payload:
        tool_name = payload["tool"]
        # Execute the tool and get result
        try:
            result = loop.run_until_complete(chat_session.process_llm_response(llm_reply))
        except Exception as e:
            result = f"Error executing tool {tool_name}: {e}"
        # Show tool output
        st.session_state.history.append({
            "role": "assistant",
            "content": f"**Tool `{tool_name}` output:** {result}"
        })

        # Feed tool JSON and result back to LLM for final answer
        st.session_state.messages.append({"role": "assistant", "content": llm_reply})
        st.session_state.messages.append({"role": "system", "content": result})
        try:
            final_reply = loop.run_until_complete(
                loop.run_in_executor(None, llm_client.get_response, st.session_state.messages, None)
            )
        except Exception as e:
            st.error(f"LLM error on final response: {e}")
            st.stop()
        # Show final LLM answer
        st.session_state.history.append({"role": "assistant", "content": final_reply})
        st.session_state.messages.append({"role": "assistant", "content": final_reply})
    else:
        # No tool call, show direct LLM reply
        st.session_state.history.append({"role": "assistant", "content": llm_reply})
        st.session_state.messages.append({"role": "assistant", "content": llm_reply})

    
