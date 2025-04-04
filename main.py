from langchain.agents import AgentExecutor, create_tool_calling_agent
from tools import clone_repo
from tools import process_repo
from langchain import hub
from llm import llm


tools = [clone_repo, process_repo]

agent_prompt = hub.pull("hwchase17/openai-tools-agent")
agent = create_tool_calling_agent(llm, tools, agent_prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

while True:
    user_input = input("Ask something (e.g., 'summarize a GitHub repo with a link for it') or 'x' to quit: ")
    if user_input.lower() == 'x':
        break

    result = agent_executor.invoke({"input": user_input})
    print(result['output'])