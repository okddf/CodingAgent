from langchain.tools import tool
import os
import ast
import math
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

def call_analyzer(file_path: str) -> Dict[str, List[str]]:
    """
    Analyze Python file and extract call relationships using AST
    """
    with open(file_path, 'r') as f:
        tree = ast.parse(f.read())
    
    call_map = {}
    
    class CallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            current_function = node.name
            call_map[current_function] = []
            
            for item in ast.walk(node):
                if isinstance(item, ast.Call):
                    if isinstance(item.func, ast.Name):
                        call_map[current_function].append(item.func.id)
                    elif isinstance(item.func, ast.Attribute):
                        call_map[current_function].append(item.func.attr)
    
    CallVisitor().visit(tree)
    return call_map

def generate_context(files):
    """Create project overview before deep file analysis"""
    project_summary = llm.invoke(
        "Based on these small sumamries, describe the project's purpose"
        "and main components in 3-4 sentences:\n\n" +
        "\n".join(f"{file['file_path']}: {file['scan']}" 
                 for file in files)
    ).content
    
    return project_summary,

def get_relevant_context(vector_store, code: str, current_file_path: str, k: int = 5) -> str:
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

def calculate_complexity(code: str) -> Dict[str, float]:
    """Calculate various complexity metrics for a code snippet"""

    tree = ast.parse(code)

    cyclomatic = 1
    operators = set()
    operands = set()
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.And, ast.Or)):
            cyclomatic += 1
        if isinstance(node, ast.With):
            cyclomatic += 1
        if isinstance(node, ast.Try):
            cyclomatic += len(node.handlers) + (1 if node.finalbody else 0)
            
        if isinstance(node, ast.operator):
            operators.add(type(node).__name__)
        elif isinstance(node, ast.cmpop):
            operators.add(type(node).__name__)
        elif isinstance(node, ast.boolop):
            operators.add(type(node).__name__)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            operands.add(node.id)
        elif isinstance(node, ast.Constant):
            operands.add(repr(node.value))
    
    n1 = len(operators)
    n2 = len(operands)
    N1 = sum(1 for _ in ast.walk(tree) if isinstance(node, ast.operator))
    N2 = sum(1 for _ in ast.walk(tree) if isinstance(node, (ast.Name, ast.Constant)))
    
    if (n1 + n2) == 0 or (N1 + N2) == 0:
        halstead_volume = 0
    else:
        halstead_volume = (N1 + N2) * math.log2(n1 + n2) if (n1 + n2) > 0 else 0
    
    depth = 0
    current_depth = 0
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For, ast.While, ast.With, ast.Try)):
            current_depth += 1
            depth = max(depth, current_depth)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For, ast.While, ast.With, ast.Try)):
            current_depth -= 1
    
    score = cyclomatic * 0.4 + halstead_volume * 0.0001 + depth * 0.3
    
    return {
        'cyclomatic': cyclomatic,
        'halstead_volume': halstead_volume,
        'depth': depth,
        'score': score
    }

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

    callmap = call_analyzer(file_path)
    context = get_relevant_context(vector_store, code, file_path)
    complexity = calculate_complexity(code)

    if file_extension == '.py':
        elements = extract_elements_with_parser(code)
    else:
        elements = extract_elements_with_llm(code, file_extension)
    
    for element in elements:
        element_complexity = calculate_complexity(element["code"])
        element["complexity"] = element_complexity

    PROMPT = PromptTemplate.from_template(
        "Describe this file's role in the project and summarize the content of it in 1 sentence.\n"
        "Focus only on the core functionality and the place of this file in the project.\n"
        "If this component uses other components from the project highlight their connection"
        "Avoid introductory phrases and implementation details.\n\n"
        "Code:\n{code}\n\n"
        "Related context: {context}\n"
        "Project context: {project_context}"
        "callmap: {callmap}"
    )

    file_summary = llm.invoke(PROMPT.format(code=code, context=context, project_context = project_context, callmap = callmap))
    
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
        "callmap": callmap,
        "code": code,
        "complexity": complexity
    }

@tool()
def create_markdown_documentation(docs: list, output_file: str) -> str:
    '''
    Creates a Markdown documentation file with summaries and Mermaid diagrams.
    
    Args:
        summaries: List of dictionaries with documents
        output_file: Path to save the Markdown file
    '''

    file_paths = []
    summaries = []
    elements = []
    callmaps = []
    complexitys = []
    for doc in docs:
        file_paths.append(doc["file_path"])
        summaries.append(doc["summary"])
        elements.append(doc["elements"])
        callmaps.append(doc["callmap"])
        complexitys.append(doc["complexity"])

    parser = JsonOutputParser()
    PROJECT_OVERVIEW_PROMPT = (
        "Highlight whats the project doing, summarize the project"
        "Write 2-3 sentences"
        "For reference:"
        "files in the project : {file_paths}"
        "summaries of the files: {summaries}"
        "elements in the files: {elements}"
        "callmaps of the elemnts in the files: {callmaps}"
    )

    ACTIVITY_PROMPT = (
        "Create a mermaid activity diagramm of the project"
        "For reference:"
        "files in the project : {file_paths}"
        "summaries of the files: {summaries}"
        "elements in the files: {elements}"
        "callmaps of the elemnts in the files: {callmaps}"
        "Return strictly only the mermaid code in this format:"
        "```mermaid\ngraph TD...\n"
        "```"
    )

    overview = llm.invoke(PROJECT_OVERVIEW_PROMPT.format(file_paths=file_paths, summaries=summaries, elements = elements, callmaps = callmaps))
    activity = llm.invoke(ACTIVITY_PROMPT.format(file_paths=file_paths, summaries=summaries, elements = elements, callmaps = callmaps))

    COMPONENT_PROMPT = (
        "List out the components of this project"
        "Write a small summary(1 sentence) to each component, highlight their role and functionality"
        "For reference:"
        "files in the project : {file_paths}"
        "summaries of the files: {summaries}"
        "elements in the files: {elements}"
        "callmaps of the elemnts in the files: {callmaps}"
        "Return ONLY the list and nothing else:"
    )

    SYSTEM_PROMPT = (
        "Create a Component Diagram mermaid diagramm of the components of the project"
        "For reference:"
        "components the project : {components}"
        "files in the project : {file_paths}"
        "summaries of the files: {summaries}"
        "elements in the files: {elements}"
        "callmaps of the elemnts in the files: {callmaps}"
        "Return ONLY the mermaid code in this format and nothing else:"
        "```mermaid\ngraph TD...\n"
        "```"
    )

    components = llm.invoke(COMPONENT_PROMPT.format(file_paths=file_paths, summaries=summaries, elements = elements, callmaps = callmaps))
    system = llm.invoke(SYSTEM_PROMPT.format(components=components, file_paths=file_paths, summaries=summaries, elements = elements, callmaps = callmaps))

    CORE_PROMPT = (
        "Find the core function of this project"
        "Highlight this core function or main workflow and write a 2 sentence explanation of it"
        "For reference:"
        "project overview: {overview}"
        "files in the project : {file_paths}"
        "summaries of the files: {summaries}"
        "elements in the files: {elements}"
        "callmaps of the elemnts in the files: {callmaps}"
    )

    SEQUENCE_PROMPT = (
        "Create a Sequence mermaid diagramm of the core workflow of the project, based on the callmap"
        "Use the exact names of the functions and files"
        "Show how the functions call each other in the main workflow"
        "For reference:"
        "core function of the project : {core}"
        "files in the project : {file_paths}"
        "summaries of the files: {summaries}"
        "elements in the files: {elements}"
        "callmaps of the elemnts in the files: {callmaps}"
        "Return ONLY the mermaid code in this format and nothing else:"
        "```mermaid\ngraph TD...\n"
        "```"
    )

    core = llm.invoke(CORE_PROMPT.format(overview = overview, file_paths=file_paths, summaries=summaries, elements = elements, callmaps = callmaps))
    sequence = llm.invoke(SEQUENCE_PROMPT.format(core=core, file_paths=file_paths, summaries=summaries, elements = elements, callmaps = callmaps))




    SNIPPET_COLLECTION_PROMPT = PromptTemplate.from_template("""
        You are documenting a codebase for developers. Only document code that meets ALL these criteria:
        1. Implements non-trivial business logic
        2. Contains complex algorithms
        3. Has non-obvious implementation details
        4. Complexity score > 3.0

        ABSOLUTELY IGNORE:
        - Import statements
        - Configuration/setup code
        - Simple variable assignments
        - Environment loading
        - Basic class/function initialization
        - Any code that just calls a library function without customization

        For code worth documenting:
        1. Extract the exact code (10-15 lines maximum)
        2. Write exactly 1 concise sentence explaining why it's significant

        Project context: {project_summary}
        File purpose: {file_summary}
                                                             
        Complexity Metrics for Reference:
        {complexity_metrics}

        Output ONLY this JSON format with NO other text:
        {{
            "sections": [
                {{
                    "code": "significant code",
                    "explanation": "exactly 1 sentence"
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
    for file_docs in docs:
        try:
            analysis = chain.invoke({
                "complexity_metrics": file_docs["complexity"],
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
        md_file.write("# Overview\n\n")
        md_file.write(overview.content + "\n\n")
        md_file.write(activity.content + "\n\n")
        md_file.write("# Architecture\n\n")
        md_file.write(components.content + "\n\n")
        md_file.write(system.content + "\n\n")
        md_file.write("# Core Functionality\n\n")
        md_file.write(core.content + "\n\n")
        md_file.write(sequence.content + "\n\n")
        
        md_file.write("# Project Components\n\n")
        for file_data in analyzed_files:
            md_file.write(f"## `{file_data['file_path']}`\n\n")
            md_file.write("### File Overview\n")
            md_file.write(f"{file_data['summary']}\n\n")

            if len(file_data["analysis"]["sections"])>0:
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

    docs = []
    
    for file in files:
        processed = process_file(file['file_path'], file['content'], vector_store, project_context)
        docs.append(processed)

    create_markdown_documentation.invoke({
        "docs": docs,
        "output_file": os.path.join(output_dir, "documentation.md")
    })