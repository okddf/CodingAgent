from langchain.agents import AgentExecutor, create_tool_calling_agent
from tools import process_repo
from llm import llm
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage


tools = [process_repo]

custom_prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content="""You are an AI agent whose job is to create documentation for codebases.
                  The goal is to create documentation from codebases so that new developers can instantly understand the whole project 
                  and they are able to contribute to it. The style of your messages therefore need to sound like the user is
                  reading a logical documentation, and the documentation should feel like a human wrote it, so
                  don't use phrases that an llm answer would contain when you are giving summarys. Always strictly follow the
                  syntax rules and never add any undesired explanation to your answer."""),
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