# NOTE: This script requires Streamlit to run.
import sys
import asyncio
import json, html, re

# Protect Streamlit import from environments where it's unavailable
try:
    import streamlit as st
except ModuleNotFoundError:
    raise ImportError("Streamlit is not installed in this environment. Please install it via `pip install streamlit`.")

from main import Configuration, Server, LLMClient, ChatSession

# Streamlit page config
st.set_page_config(page_title="MCP Chatbot", layout="wide")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

st.title("\U0001F4AC MCP Chatbot")

# Chat UI CSS
st.markdown(
    '''
    <style>
    html, body, .stApp {
        background: linear-gradient(to bottom right, #f2f9ff, #e6f7ff);
    }
    .chat-container {
        display: flex;
        margin: 4px 0;
        align-items: center;
        gap: 4px;
    }
    .user-bubble {
        background-color: #DCF8C6;
        color: #000;
        padding: 12px;
        border-radius: 16px 16px 0 16px;
        max-width: 60%;
        margin-left: auto;
    }
    .assistant-bubble {
        background-color: #FFF;
        color: #000;
        padding: 12px;
        border-radius: 16px 16px 16px 0;
        max-width: 60%;
        margin-right: auto;
    }
    .chat-container img.avatar {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        margin: 0;
    }
    </style>
    ''', unsafe_allow_html=True
)

scroll_script = """
<script>
window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'});
</script>
"""

@st.cache_resource
def init_chat_backend():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = Configuration()
    server_cfg = Configuration.load_config("servers_config.json")
    servers = [Server(name, cfg) for name, cfg in server_cfg["mcpServers"].items()]
    for srv in servers:
        loop.run_until_complete(srv.initialize())
    llm = LLMClient(config.llm_api_key, servers)
    loop.run_until_complete(llm.initialize_tools())
    chat_session = ChatSession(servers, llm)
    return loop, servers, llm, chat_session

loop, servers, llm_client, chat_session = init_chat_backend()

if "messages" not in st.session_state:
    tools = []
    for srv in servers:
        tools.extend(loop.run_until_complete(srv.list_tools()))
    desc = "\n".join(t.format_for_llm() for t in tools)
    system_msg = (
        "You are a helpful assistant with real access to these tools:\n\n"
        f"{desc}\n"
        "Choose the appropriate tool based on the user's question and execute the tool to perform the action. "
        "if a tool does not work, explain the error to the user and suggest a different tool. You must never simulate the tool.\n\n"
        "When the user asks for data involving multiple elements (e.g. multiple cities), you should loop over them, calling the tool for each."
        "If a tool does not work, explain the error and suggest a different tool.\n\n"
        "IMPORTANT: When you need to use a tool, you must ONLY respond with "
        "the exact JSON object format below, nothing else:\n"
        "{\n"
        '    "tool": "tool-name",\n'
        '    "arguments": {\n'
        '        "argument-name": "value"\n'
        "    }\n"
        "}\n\n"
        "DO NOT include any <function=...> or </function> tags.\n"
        "DO NOT wrap JSON in quotes.\n"
        "DO NOT return multiple tool calls in a single message. Only return ONE JSON object per response.\n"
        "If no tool is needed, respond in plain natural language.\n"
        "After receiving a tool's response:\n"
        "1. Transform the raw data into a natural, conversational response\n"
        "2. Keep responses concise but informative\n"
        "3. Focus on the most relevant information\n"
        "4. Use appropriate context from the user's question\n"
        "5. Avoid simply repeating the raw data\n\n"
        "Please use only the tools that are explicitly defined above."
    )
    st.session_state.messages = [{"role": "system", "content": system_msg}]
    st.session_state.history = []

# Render full conversation history
for entry in st.session_state.history:
    role = entry["role"]
    content = html.escape(entry["content"])
    if role == "user":
        avatar = '<img class="avatar" src="https://cdn-icons-png.flaticon.com/512/4086/4086679.png" />'
        bubble = f'<div class="chat-container">{avatar}<div class="user-bubble">{content}</div></div>'
    else:
        avatar = '<img class="avatar" src="https://gimgs2.nohat.cc/thumb/f/350/svg-chatbot-icon--freesvgorg133669.jpg" />'
        bubble = f'<div class="chat-container"><div class="assistant-bubble">{content}</div>{avatar}</div>'
    st.markdown(bubble, unsafe_allow_html=True)

user_text = st.chat_input("You:")
if user_text:
    st.session_state.history.append({"role": "user", "content": user_text})
    st.session_state.messages.append({"role": "user", "content": user_text})
    st.markdown(f'<div class="chat-container"><img class="avatar" src="https://cdn-icons-png.flaticon.com/512/4086/4086679.png" /><div class="user-bubble">{html.escape(user_text)}</div></div>', unsafe_allow_html=True)

    with st.spinner("Thinking..."):
        max_exchanges = 10
        system_msg = st.session_state.messages[0]
        recent = st.session_state.messages[-(max_exchanges * 2):]
        payload_msgs = [system_msg] + recent
        llm_reply = llm_client.get_response(payload_msgs)

        while True:
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

                st.session_state.history.append({"role": "assistant", "content": llm_reply})
                st.session_state.messages.append({"role": "assistant", "content": llm_reply})
                st.markdown(f'<div class="chat-container"><div class="assistant-bubble">{html.escape(llm_reply)}</div><img class="avatar" src="https://gimgs2.nohat.cc/thumb/f/350/svg-chatbot-icon--freesvgorg133669.jpg" /></div>', unsafe_allow_html=True)

                st.session_state.history.append({"role": "system", "content": result})
                st.session_state.messages.append({"role": "system", "content": result})
                st.markdown(f'<div class="chat-container"><div class="assistant-bubble">{html.escape(result)}</div><img class="avatar" src="https://gimgs2.nohat.cc/thumb/f/350/svg-chatbot-icon--freesvgorg133669.jpg" /></div>', unsafe_allow_html=True)

                recent = st.session_state.messages[-(max_exchanges * 2):]
                payload_msgs = [system_msg] + recent
                llm_reply = llm_client.get_response(payload_msgs)
                continue
            else:
                break

        st.session_state.history.append({"role": "assistant", "content": llm_reply})
        st.session_state.messages.append({"role": "assistant", "content": llm_reply})
        st.markdown(f'<div class="chat-container"><div class="assistant-bubble">{html.escape(llm_reply)}</div><img class="avatar" src="https://gimgs2.nohat.cc/thumb/f/350/svg-chatbot-icon--freesvgorg133669.jpg" /></div>', unsafe_allow_html=True)

    st.components.v1.html(scroll_script, height=0)
