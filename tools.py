from langchain.tools import tool
import os
from langchain.prompts import PromptTemplate
from llm import llm
import fnmatch
from typing import List, Dict
from langchain_core.output_parsers.json import JsonOutputParser
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import Runnable
import json
from parser import extract_elements_with_parser, extract_elements_with_llm
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=100,
    chunk_overlap=50,
    separators=["\nclass ", "\ndef ", "\n\n", "\n"]
)

CLASS_TEMPLATE = """## `{class_name}`
{description}

**Methods**:
{methods_list}"""

FUNCTION_TEMPLATE = """## `{function_name}({params}) -> {return_type}`
{description}

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
{params_table}

**Returns**:
| Type | Description |
|------|-------------|
{returns_table}"""

def create_vector_store(files):
    """Create during repo processing"""
    documents = []
    
    for file in files:
        chunks = TEXT_SPLITTER.split_text(file['content'])
        for chunk in chunks:
            documents.append(Document(
                page_content=chunk,
                metadata={"file_path": file['file_path']}
            ))
    
    return FAISS.from_documents(documents, OpenAIEmbeddings())

def scan(repo_path: str):
    """First pass: Collect raw file contents and basic structure"""
    files = split_repo.invoke({"repo_path": repo_path})
    vector_store = create_vector_store(files)
    
    PROMPT = PromptTemplate.from_template(
        "In 10 words or a sentence, what does the file contain, calsses or functions that do what?\n"
        "Code:\n{code}\n\n"
    )

    preliminary_docs = []
    for file in files:
        preliminary_docs.append({
            "file_path": file['file_path'],
            "content": file['content'],
            "scan": llm.invoke(PROMPT.format(code=file['content'])).content
        })
    
    return preliminary_docs, vector_store

def generate_context(files):
    """Create project overview before deep file analysis"""
    project_summary = llm.invoke(
        "Based on these small sumamries, describe the project's purpose"
        "and main components in 3-4 sentences:\n\n" +
        "\n".join(f"{file['file_path']}: {file['scan']}" 
                 for file in files)
    ).content
    
    return project_summary,

def get_relevant_context(vector_store, code: str, current_file_path: str, k: int = 3) -> str:
    """Retrieve relevant code snippets from other files"""
    results = vector_store.similarity_search(code, k=k)
    context = []
    
    for doc in results:
        if doc.metadata['file_path'] != current_file_path:
            context.append(
                f"From {doc.metadata['file_path']}:\n"
                f"{doc.page_content}\n"
                f"{'-'*40}"
            )
    
    return "\n".join(context) if context else "No relevant context found"

@tool()
def identify_excludable_files(file_paths: list) -> list:
    '''
    Identifies files that should be excluded from documentation generation.

    Args:
        file_paths: A list of file paths in the repository.
    '''

    docignore_path = '.docignore'
    EXCLUDE_PATTERNS = []

    with open(docignore_path, 'r') as f:
        EXCLUDE_PATTERNS = [line.strip() for line in f if line.strip()]

    excluded_files = []
        
    for file_path in file_paths:
        normalized_path = file_path.replace(os.sep, '/')
        basename = os.path.basename(file_path)
        if basename.startswith('.'):
            excluded_files.append(file_path)
            continue
            
        excluded = False
        for pattern in EXCLUDE_PATTERNS:
            if pattern.endswith('/'):
                dir_pattern = pattern.rstrip('/')
                if dir_pattern in normalized_path.split('/'):
                    excluded = True
                    break
            elif '*' in pattern:
                if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(normalized_path, pattern):
                    excluded = True
                    break
            elif pattern == basename or pattern in normalized_path.split('/'):
                excluded = True
                break
        
        if excluded:
            excluded_files.append(file_path)
    
    print(excluded_files)
    return excluded_files

@tool()
def split_repo(repo_path: str) -> list:
    '''
    Splits the repository into logical parts (file by file) to summarize it.
    Preserves original file formatting for accurate parsing.
    '''
    file_paths = []
    for root, dirs, files in os.walk(repo_path):
        if '.git' in dirs:
            dirs.remove('.git')
        for file in files:
            file_paths.append(os.path.join(root, file))
    
    file_paths = [os.path.relpath(path, repo_path) for path in file_paths]
    excludable_files = identify_excludable_files.invoke({"file_paths": file_paths})

    filtered_files = []
    for file_path in file_paths:
        abs_path = os.path.join(repo_path, file_path)
        basename = os.path.basename(file_path)
        
        if file_path in excludable_files:
            continue
        if basename.startswith('.'):
            continue
            
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
            filtered_files.append({
                "file_path": file_path,
                "content": content
            })
        except (UnicodeDecodeError, IOError) as e:
            print(f"Skipping {file_path} due to error: {e}")
    
    return filtered_files

def generate_structured_docs(element: dict, file_extension: str) -> str:
    parser = JsonOutputParser()
    prompt = None
    if element["type"] == "class":
        prompt = PromptTemplate.from_template("""
        Create a strucutured class api documentation from this {file_extension} class:
        Extract the following information:
        1. Class name
        2. A small description of the functionality of this class
        3. All methods with the following:
            1. Function name
            2. A small description of the functionality of this function
            3. All parameters with types and default value if they are available
            4. Return type and a small description of this piece of data if available

        Class code:
        {code}
                                              
        Class name:
        {name}
                                              
        Class methods:
        {methods}

        Your output MUST be valid JSON in this exact format and contain NO explanation, commentary, or extra text
        If there are no parameters you can return an empty list there, same with returns with empty dictionary.
        Return ONLY the raw JSON code and nothing else in strictly this format:
        {{
            "class_name": "...",
            "description": "...",
            "methods": [
                {{"name": "method1", "params": [{{"name": "param1", "type": "str", "default": "None", "description": "..."}}], "returns": {{"type": "return_type", "description": "..."}}}}
            ]
        }}""")

        chain: Runnable = prompt | llm | parser
        try:
            data = chain.invoke({"code": element["code"], "name": element["name"], "methods": element["methods"], "file_extension": file_extension})
        except Exception as e:
            print(f"Error parsing structured output: {e}")
            return f"**Error generating docs for this {element["type"]}**"

        methods_list = []
        for method in data["methods"]:
            params_table = "\n".join(
                f"| `{param['name']}` | `{param.get('type', '')}` | `{param.get('default', '')}` | {param['description']} |"
                for param in method.get("params", [])
            )

            returns_table = f"| `{method['returns'].get('type', 'void')}` | {method['returns'].get('description', '')} |"

            formatted_method = FUNCTION_TEMPLATE.format(
                language=file_extension,
                function_name=method.get("name", "unknown_function"),
                description=method.get("description", ""),
                params=", ".join(p.get('name', '') for p in method.get("params", [])),
                return_type=method['returns'].get('type', 'void'),
                params_table=params_table,
                returns_table=returns_table
            )

            methods_list.append(f"\n{formatted_method}\n")

        methods_section = "\n---\n".join(methods_list)
        return CLASS_TEMPLATE.format(
            language=file_extension,
            class_name=data.get("class_name", "UnknownClass"),
            description=data.get("description", ""),
            methods_list=methods_section
        )
    
    elif element["type"] == "function":
        prompt = PromptTemplate.from_template("""
        Create a strucutured function api documentation from this {file_extension} function:
        Extract the following information:
        1. Function name
        2. A small description of the functionality of this function
        3. All parameters with types and default value if available
        4. Return type and a small description of this piece of data

        Function code:
        {code}
        
        Function name:
        {name}
                                              
        function parameters:
        {parameters}
                                              
        Your output MUST be valid JSON in this exact format and contain NO explanation, commentary, or extra text
        If there are no parameters you can return an empty list there, same with returns.
        Return ONLY the raw JSON code and nothing else in strictly this format:
        {{
            "function_name": "...",
            "description": "...",
            "params": [
                {{"name": "param1", "type": "str", "default": "None", "description": "..."}}
            ],
            "returns": {{"type": "return_type", "description": "..."}}
        }}""")

        chain: Runnable = prompt | llm | parser
        try:
            data = chain.invoke({"code": element["code"], "name": element["name"], "parameters": element["parameters"], "file_extension": file_extension})
        except Exception as e:
            print(f"Error parsing structured output: {e}")
            return f"**Error generating docs for this {element["type"]}**"
        
        params_table = "\n".join(
            f"| `{param['name']}` | `{param.get('type', '')}` | `{param.get('default', '')}` | {param['description']} |"
            for param in data.get("params", [])
        )
        
        returns_table = f"| `{data['returns'].get('type', 'void')}` | {data['returns'].get('description', '')} |"
        
        return FUNCTION_TEMPLATE.format(
            language=file_extension,
            function_name=data.get("function_name", "unknown_function"),
            description=data.get("description", ""),
            params=", ".join(p.get('name', '') for p in data.get("params", [])),
            return_type=data['returns'].get('type', 'void'),
            params_table=params_table,
            returns_table=returns_table
        )

def process_file(file_path: str, code: str, vector_store, project_context) -> Dict:
    """
    Create structured documentation for a file.
    """
    print(f"Analyzing {file_path}")
    file_extension = os.path.splitext(file_path)[1]

    rag_context = ""
    if vector_store:
        rag_context = get_relevant_context(vector_store, code, file_path)
        print(f"Found relevant context for {file_path}:\n{rag_context[:200]}...")

    if file_extension == '.py':
        elements = extract_elements_with_parser(code)
    else:
        elements = extract_elements_with_llm(code, file_extension)

    PROMPT = PromptTemplate.from_template(
        "Describe this file's role in the project and summarize the content of it in 1 sentence.\n"
        "Focus only on the core functionality and the place of this file in the project\n"
        "Avoid introductory phrases and implementation details.\n\n"
        "Code:\n{code}\n\n"
        "Related context: {context}\n"
        "Project context: {project_context}"
    )

    file_summary = llm.invoke(PROMPT.format(code=code, context=rag_context, project_context = project_context))
    
    processed_elements = []
    for element in elements:
        docs = generate_structured_docs(element, file_extension)
        processed_elements.append({
            **element,
            "docs": docs
        })
    
    return {
        "file_path": file_path,
        "summary": file_summary.content,
        "elements": processed_elements,
        "code": code
    }

@tool()
def create_markdown_documentation(summaries: list, output_file: str) -> str:
    '''
    Creates a Markdown documentation file with summaries and Mermaid diagrams.
    
    Args:
        summaries: List of dictionaries with 'file_path' and 'summary'
        output_file: Path to save the Markdown file
    '''
    parser = JsonOutputParser()
    PROJECT_OVERVIEW_PROMPT = (
        "You are creating the project overview documentation for a codebase."
        "Generate a comprehensive project overview using the following file summaries. "
        "The overview should include:\n"
        "1. **Project Purpose**: A clear description of what the project does and its main objectives.\n"
        "2. **Key Components**: A breakdown of modules and their roles.\n"
        "3. **Interaction Flow**: How components work together (e.g., data flow, control flow). Who relies on who to achieve what\n"
        "4. **Activity Diagram**: A Mermaid.js-compatible detailed description of the entire workflow so that how the code works, who calls who and why, include every function call.\n\n"
        "Write in natural, documentation-friendly prose—avoid phrases like 'the provided files' or 'as we can see'.\n\n"
        "File Summaries:\n"
        f"{summaries}\n\n"
        "Follow this Output Structure and onlz return this and nothing else:\n"
        "# Project Overview\n\n"
        "## Purpose\n<2-3 sentences>\n\n"
        "## Components\n<bullet list of major components>\n\n"
        "## Interactions\n<brief explanation of how components connect>\n\n"
        "```mermaid\ngraph TD\n<flow logic>\n```\n"
        "```"
    )

    overview = llm.invoke(PROJECT_OVERVIEW_PROMPT)

    SNIPPET_COLLECTION_PROMPT = PromptTemplate.from_template("""
    You are documenting a codebase for developers who need to understand the code to contribute effectively. 
    Your task is to analyze the code and identify *only the most significant sections* that require explanation. 
    IMPORTANT YOUR JOB IS NOT TO TRANSLATE CODE INTO HUMAN LANGUAGE, YOUR JOB IS TO EXPLAIN NON-TRIVIAL DEVELOPER CHOICES.
    IGNORE trivial code such as:
    - Simple variable declarations (e.g., `x = 5`)
    - Basic return statements (e.g., `return x`)
    - Standard boilerplate (e.g., imports)
    - Obvious or self-explanatory code

    For each significant section:
    1. Extract the corresponding lines of code.
    2. Provide a concise explanation that covers:
    - What the code does and why it matters in the context of the file/project.
    - Any non-obvious design decisions or implementation details.
    - How it interacts with other parts of the codebase (if relevant).

    Project context: {project_summary}
    File purpose: {file_summary}

    Your output MUST be valid JSON in this exact format and contain NO extra text:
    {{
        "sections": [
            {{
                "code": "The code that is being explained",
                "explanation": "Concise, developer-focused explanation"
            }}
        ]
    }}

    Code:
    {code}
    """)
    
    DOCUMENTATION_GENERATION_PROMPT = """
    You are creating professional documentation for a codebase, guiding a new developer through the code in a clear, concise, and insightful way. 
    Your task is to write a narrative that explains the file's key functionality, focusing only on the most significant code sections (provided in the analysis). 
    Avoid explaining trivial details like simple variable assignments, return statements, or boilerplate code. 
    Instead, emphasize:
    - The purpose of the code and its role in the project.
    - How the significant sections contribute to the file's functionality.
    - Any complex logic, design decisions, or interactions with other parts of the codebase.

    Write in a professional, tutorial-style tone, as if this is part of a larger project documentation. 
    Do not walk through the entire code line-by-line; instead, weave the provided code snippets into a cohesive explanation of the file's purpose and key operations. 
    Use markdown format for code blocks, but do not include titles or headers—just the narrative and code.

    Keep it simple and short, only write a few words to each concept or section

    Project context: {project_summary}
    File summary: {file_summary}
    Code analysis: {analysis}
    """

    chain: Runnable = SNIPPET_COLLECTION_PROMPT | llm | parser
    
    analyzed_files = []
    for file_docs in summaries:
        try:
            analysis = chain.invoke({
                "project_summary": overview.content, 
                "file_summary": file_docs['summary'], 
                "code": file_docs['code']
            })
            analyzed_files.append({
                "file_path": file_docs['file_path'],
                "summary": file_docs['summary'],
                "analysis": analysis,
                "elements": file_docs.get('elements', [])
            })
        except Exception as e:
            print(f"Error parsing structured output for {file_docs['file_path']}: {e}")
            analyzed_files.append({
                "file_path": file_docs['file_path'],
                "summary": file_docs['summary'],
                "analysis": {"sections": []},
                "elements": file_docs.get('elements', [])
            })

    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as md_file:
        md_file.write("# Documentation\n\n")
        md_file.write(overview.content + "\n\n")
        
        md_file.write("# Project Components\n\n")
        for file_data in analyzed_files:
            md_file.write(f"## `{file_data['file_path']}`\n\n")
            md_file.write("### File Overview\n")
            md_file.write(f"{file_data['summary']}\n\n")

            docs = llm.invoke(
                PromptTemplate.from_template(DOCUMENTATION_GENERATION_PROMPT).format(
                    project_summary = overview.content,
                    file_summary=file_data['summary'],
                    analysis=json.dumps(file_data['analysis'])
                )
            )
            md_file.write(docs.content + "\n\n")
            
            elements_to_document = [
                element for element in file_data['elements'] 
                if element['type'] in ('class', 'function')
            ]

            if elements_to_document:
                md_file.write("### Functions and Classes\n\n")
                for element in file_data['elements']:
                    if element['type'] in ('class', 'function'):
                        md_file.write(element['docs'] + "\n\n")
        
    return f"Markdown documentation created at {output_file}"

@tool()
def process_repo(repo_path: str, output_dir: str) -> str:
    '''
    Processes a repository file by file, generates documentation in Markdown format
    with embedded Mermaid diagrams.

    Args:
        repo_path: Path to the local repository directory
        output_dir: Directory to save the documentation
    '''

    files, vector_store = scan(repo_path=repo_path)
    project_context = generate_context(files)

    all_docs = []
    
    for file in files:
        processed = process_file(file['file_path'], file['content'], vector_store, project_context)
        all_docs.append(processed)

    create_markdown_documentation.invoke({
        "summaries": all_docs,
        "output_file": os.path.join(output_dir, "documentation.md")
    })