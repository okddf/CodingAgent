from langchain.tools import tool
from langchain_community.document_loaders import DirectoryLoader
import os
import ast
from langchain.prompts import PromptTemplate
from llm import llm
import fnmatch
from typing import List, Dict
from langchain_core.output_parsers.json import JsonOutputParser
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import Runnable
import json
from tree_sitter import Language, Parser
import tree_sitter_python as tspython

PYTHON_LANGUAGE = Language(tspython.language())

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

def initialize_parser():
    parser = Parser(PYTHON_LANGUAGE)
    return parser

def extract_elements_with_parser(code: str, parser) -> List[Dict]:
    """
    Extract classes and functions using tree-sitter.
    """
    elements = []
    method_names = []
    tree = parser.parse(bytes(code, "utf8"))

    query = PYTHON_LANGUAGE.query("""
    (function_definition
      (identifier)@name
      (parameters)@parameters
      (block)@block
    ) @function
    
    (class_definition
      (identifier)@classname
      (block
        (function_definition)@method
      )@classblock
    ) @class
    """)


    captures = query.captures(tree.root_node)

    try:
        captures["class"]
        classes = True
    except:
        classes = False

    try:
        captures["function"]
        functions = True
    except:
        functions = False

    if len(captures) > 0:
        if classes:
            for i in range(len(captures["class"])):
                for child in captures["class"][i].children:
                    if child.type == 'identifier':
                        class_name = child.text.decode('utf8') 
                    if child.type == 'block':
                        class_block = child.text.decode('utf8') 

                        method_query = PYTHON_LANGUAGE.query("""
                        (function_definition
                        name: (identifier) @methodname
                        parameters: (parameters) @methodparams
                        body: (block) @methodbody
                        ) @method
                        """)
                    
                        method_captures = method_query.captures(child)
                        methods = []

                        for i in range(len(method_captures["method"])):
                            for classchild in method_captures["method"][i].children:
                                if classchild.type == 'identifier':
                                    method_name = classchild.text.decode('utf8') 
                                    method_names.append(method_name)
                                if classchild.type == 'parameters':
                                    method_parameters = classchild.text.decode('utf8') 
                                if classchild.type == 'block':
                                    method_block = classchild.text.decode('utf8')
                        
                        methods.append({
                            "name": method_name,
                            "parameters": method_parameters,
                            "code": method_block
                        })

                elements.append({
                    "type": "class",
                    "name": class_name,
                    "methods": methods,
                    "code": class_block
                })

        if functions:
            for i in range(len(captures["function"])):
                for child in captures["function"][i].children:
                    if child.type == 'identifier':
                        function_name = child.text.decode('utf8') 
                    if child.type == 'parameters':
                        parameters = child.text.decode('utf8') 
                    if child.type == 'block':
                        block = child.text.decode('utf8') 

                if function_name in method_names:
                    continue

                elements.append({
                    "type": "function",
                    "name": function_name,
                    "parameters": parameters,
                    "code": block
                })
        
    return elements

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

def extract_elements_with_llm(code: str, file_extension: str) -> List[Dict]:
    """
    Extract code elements using text-based format
    """
    prompt = f"""You are documenting a {file_extension} codebase. Extract ONLY class/function definitions THAT ARE DEFINED IN THIS FILE.
    If there is no such definition simply return a message saying you didn't find any.

    IGNORE:
    - Imported classes/functions (e.g., `from x import Y`)
    - Instantiations (`x = ClassName()`)
    - Function calls (`function_name()`)
    - Decorators (unless part of the definition)
    - Comments/docstrings (keep them only if they're inside the definition)

    OUTPUT FORMAT:
    === ELEMENT ===
    Type: class or function depending on the element type
    Name: the name of the defined element
    Code: full code of the element
    === END ELEMENT ===

    CODE TO ANALYZE:
    {code}"""
    
    response = llm.invoke(prompt).content
    return parse_elements_from_text(response)

def parse_elements_from_text(text: str) -> List[Dict]:
    """Parse the text response into structured elements"""
    elements = []
    current_element = {}
    
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith("=== ELEMENT ==="):
            current_element = {}
        elif line.startswith("Type:"):
            current_element["type"] = line.split(":", 1)[1].strip()
        elif line.startswith("Name:"):
            current_element["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Code:"):
            current_element["code"] = ""
        elif line.startswith("=== END ELEMENT ==="):
            if current_element:
                current_element["code"] = current_element["code"].strip()
                elements.append(current_element)
        elif "code" in current_element:
            current_element["code"] += line + "\n"
    
    return elements

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

            methods_list.append(formatted_method)

        return CLASS_TEMPLATE.format(
            language=file_extension,
            class_name=data.get("class_name", "UnknownClass"),
            description=data.get("description", ""),
            methods_list=methods_list
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

def process_file(file_path: str, code: str) -> Dict:
    """
    Create structured documentation for a file.
    """
    print(f"Analyzing {file_path}")
    file_extension = os.path.splitext(file_path)[1]

    if file_extension == '.py':
        parser = initialize_parser()
        elements = extract_elements_with_parser(code, parser)
    else:
        elements = extract_elements_with_llm(code, file_extension)

    PROMPT = (
        "You are documenting a codebase. Analyze the given code and summarize its purpose and content. "
        "The summary should be concise yet informative, explaining what the code does without technical jargon. "
        "Write it as if it's part of natural developer documentation—avoid phrases like 'the provided code' or 'this file contains'. "
        "Make it seem like that this is part of a big documentation and this is not an alone code snippet"
        f"Here is the code to analyze: {code}"
    )

    file_summary = llm.invoke(PROMPT)
    
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

        print(elements_to_document)

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
    files = split_repo.invoke({"repo_path": repo_path})
    all_docs = []
    
    for file in files:
        processed = process_file(file['file_path'], file['content'])
        all_docs.append(processed)

    create_markdown_documentation.invoke({
        "summaries": all_docs,
        "output_file": os.path.join(output_dir, "documentation.md")
    })