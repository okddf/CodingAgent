from langchain.agents import AgentExecutor, create_tool_calling_agent
from tools import process_repo
from llm import llm
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage


tools = [process_repo]

custom_prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content="""
        You are an expert AI agent specializing in generating high-quality documentation for codebases.

        Your task is to analyze code and produce **clear, concise, and minimal documentation**.

        **Rules:**
        - Your responses must be **brief**, **on point**, and **free of unnecessary explanation**.
        - **Do not summarize obvious or self-explanatory code.**
        - Avoid repeating the same information in different words.
        - **Do not use filler phrases** like "this code is about", "the purpose of this function is", etc.
        - Use **technical language** appropriate for experienced developers.
        - Output **only what is essential to understand structure, logic, and purpose**.
        - If you don't have enough context to answer well, ask for clarification instead of guessing.

        Respond in a way that is similar to professional, well-edited documentation — precise, readable, and helpful.
    """),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

tools = [process_repo]
agent = create_tool_calling_agent(llm, tools, custom_prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

while True:
    user_input = input("Ask something (e.g., 'summarize a repo with a path for it') or 'x' to quit: ")
    if user_input.lower() == 'x':
        break

    result = agent_executor.invoke({"input": user_input})
    print(result['output'])