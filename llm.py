from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()

llm = ChatOpenAI(model= "gpt-4o-mini")
#llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", api_key="AIzaSyDQwjpqNdt6UEN0ksC6GybPXXoarmyUsXo")