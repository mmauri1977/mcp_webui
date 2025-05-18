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

# Add custom CSS for chat bubbles
st.markdown(
    '''
    <style>
    .chat-container { display: flex; margin: 8px 0; }
    .user-bubble { background-color: #DCF8C6; color: #000; padding: 12px; border-radius: 16px 16px 0 16px; max-width: 60%; margin-left: auto; }
    .assistant-bubble { background-color: #FFF; color: #000; padding: 12px; border-radius: 16px 16px 16px 0; max-width: 60%; margin-right: auto; }
    .chat-container img.avatar { width: 32px; height: 32px; border-radius: 50%; margin: 0 8px; }
    </style>
    ''', unsafe_allow_html=True
)

# 1) CACHING BACKEND INITIALIZATION
@st.cache_resource
def init_chat_backend():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config = Configuration()
    server_cfg = Configuration.load_config("servers_config.json")
    servers = [Server(name, cfg) for name, cfg in server_cfg["mcpServers"].items()]

    for srv in servers:
        loop.run_until_complete(srv.initialize())

    llm = LLMClient(config.llm_api_key)
    chat_session = ChatSession(servers, llm)
    return loop, servers, llm, chat_session

# 2) RETRIEVE CACHED BACKEND
loop, servers, llm_client, chat_session = init_chat_backend()

# Build system prompt on first run
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
        "You must NOT simulate tool execution; instead, when a tool is required, respond ONLY with the exact JSON object for the tool invocation, and nothing else. "
        "Do NOT include any sample outputs or extra commentary."
        "When no tool is needed, reply with a natural language answer."
        '{"tool":"<name>","arguments":{…}}\n'
        "Otherwise, answer as a helpful assistant."
    )
    
    st.session_state.messages = [{"role": "system", "content": system_msg}]
    st.session_state.history = []

# Display conversation history with bubbles
def display_message(role, content):
    if role == "user":
        avatar = '<img class="avatar" src="https://i.imgur.com/0D4iFPC.png" />'
        bubble = f'<div class="chat-container">{avatar}<div class="user-bubble">{content}</div></div>'
    else:
        avatar = '<img class="avatar" src="https://i.imgur.com/8Km9tLL.png" />'
        bubble = f'<div class="chat-container"><div class="assistant-bubble">{content}</div>{avatar}</div>'
    st.markdown(bubble, unsafe_allow_html=True)

for entry in st.session_state.history:
    display_message(entry["role"], entry["content"])

# Chat input from user
user_text = st.chat_input("You:")
if user_text:
    st.session_state.history.append({"role": "user", "content": user_text})
    st.session_state.messages.append({"role": "user", "content": user_text})

    try:
        llm_reply = loop.run_until_complete(
            loop.run_in_executor(None, llm_client.get_response, st.session_state.messages, None)
        )
    except Exception as e:
        st.error(f"LLM error: {e}")
        st.stop()

    try:
        payload = json.loads(llm_reply)
    except json.JSONDecodeError:
        payload = None

    if payload and "tool" in payload:
        tool_name = payload["tool"]
        try:
            result = loop.run_until_complete(chat_session.process_llm_response(llm_reply))
        except Exception as e:
            result = f"Error executing tool {tool_name}: {e}"
        st.session_state.history.append({"role": "assistant", "content": f"**Tool `{tool_name}` output:** {result}"})

        st.session_state.messages.append({"role": "assistant", "content": llm_reply})
        st.session_state.messages.append({"role": "system", "content": result})
        try:
            final_reply = loop.run_until_complete(
                loop.run_in_executor(None, llm_client.get_response, st.session_state.messages, None)
            )
        except Exception as e:
            st.error(f"LLM error on final response: {e}")
            st.stop()
        st.session_state.history.append({"role": "assistant", "content": final_reply})
        st.session_state.messages.append({"role": "assistant", "content": final_reply})
    else:
        st.session_state.history.append({"role": "assistant", "content": llm_reply})
        st.session_state.messages.append({"role": "assistant", "content": llm_reply})

    # Refresh display
    for entry in st.session_state.history:
        display_message(entry["role"], entry["content"])
