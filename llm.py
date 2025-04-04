from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatOpenAI(model= "gpt-4o-mini", api_key= "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")
#llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", api_key="AIzaSyDQwjpqNdt6UEN0ksC6GybPXXoarmyUsXo")