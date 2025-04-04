from langchain.tools import tool
from langchain_community.document_loaders import GitLoader
import git
import os
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from llm import llm
import tiktoken
import fnmatch
from typing import List, Dict
import json

tokenizer = tiktoken.get_encoding("cl100k_base")

CLASS_TEMPLATE = """## `{class_name}`
**Description**: {description}

**Attributes**:
| Name | Type | Description |
|------|------|-------------|
{attributes_table}

**Methods**:
{methods_list}

**Example Usage**:
```{language}
{example_usage}
```"""

FUNCTION_TEMPLATE = """### `{function_name}({params}) -> {return_type}`
**Description**: {description}

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
{params_table}

**Returns**:
| Type | Description |
|------|-------------|
{returns_table}

**Example Usage**:
```{language}
{example_usage}
```"""

@tool()
def clone_repo(repo_url: str, clone_dir: str = "./cloned_repo") -> str:
    '''
    Clones a GitHub repository to a specified directory.

    Args:
        repo_url: The URL of the GitHub repository.
        clone_dir: The directory to clone the repository into.
    '''
    if not os.path.exists(clone_dir):
        git.Repo.clone_from(repo_url, clone_dir)


@tool()
def identify_excludable_files(file_paths: list) -> list:
    '''
    Identifies files that should be excluded from documentation generation.

    Args:
        file_paths: A list of file paths in the repository.
    '''

    docignore_path = '.docignore'
    
    with open(docignore_path, 'r') as f:
        EXCLUDE_PATTERNS = [line.strip() for line in f ]

    excluded_files = []
    
    for file_path in file_paths:
        basename = os.path.basename(file_path)
        if basename.startswith('.') and basename not in ['.env', '.env.local']:
            excluded_files.append(file_path)
            continue
            
        for pattern in EXCLUDE_PATTERNS:
            if pattern.endswith('*') and not pattern.startswith('*'):
                dir_pattern = pattern.rstrip('*')
                if dir_pattern in file_path.split(os.sep):
                    excluded_files.append(file_path)
                    break
            elif fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(basename, pattern):
                excluded_files.append(file_path)
                break
    
    print(excluded_files)
    return excluded_files


@tool()
def split_repo(clone_dir: str) -> list:
    '''
    Splits the repository into logical parts (file by file) to summarize it.

    Args:
        clone_dir: The directory where the repository is cloned.
    '''
    loader = GitLoader(repo_path=clone_dir, branch="master")
    documents = loader.load()
    file_paths = [doc.metadata['file_path'] for doc in documents]

    excludable_files = identify_excludable_files.invoke({"file_paths": file_paths})

    filtered_documents = [doc for doc in documents if doc.metadata['file_path'] not in excludable_files and not doc.metadata['file_path'].startswith('.')]

    return [{"file_path": doc.metadata['file_path'], "content": doc.page_content} for doc in filtered_documents]


def extract_elements_with_llm(code: str, file_extension: str) -> List[Dict]:
    """
    Uses LLM to identify all code elements with their types and boundaries.
    Returns: [
        {"type": "class", "name": "ClassName", "code": "class ClassName..."},
        {"type": "function", "name": "function_name", "code": "def func..."}
    ]
    """
    prompt = f"""Analyze this {file_extension} code and identify ONLY classes and functions. Return STRICTLY as JSON with NO other text or explanations.
    
    Required format:
    {{
        "elements": [
            {{
                "type": "class|function",
                "name": "ElementName",
                "code": "FullElementCode"
            }}
        ]
    }}

    Rules:
    1. Only include classes and functions
    2. Skip all imports, comments, and other code
    3. Return raw JSON without markdown formatting
    4. Include complete code blocks

    Code to analyze:
    {code}"""
    
    llm_response = llm.invoke(prompt)
    json_str = llm_response.content.strip()
    if json_str.startswith('```json'):
        json_str = json_str[7:-3].strip()
    elif json_str.startswith('```'):
        json_str = json_str[3:-3].strip()
        
    data = json.loads(json_str)
    return data["elements"]
    

def process_file(file_path: str, code: str) -> Dict:
    """
    Handles both LLM analysis and structured documentation generation.
    Returns: {
        "file_path": "path/to/file.py",
        "summary": "File purpose...",
        "elements": [
            {
                "type": "class",
                "name": "A",
                "docs": "Class docs...",
                "code": "class A: ..."
            }
        ]
    }
    """
    print(f"Analyzing {file_path}")
    file_extension = os.path.splitext(file_path)[1]
    elements = extract_elements_with_llm(code, file_extension)

    file_summary = llm.invoke(
        f"Summarize this file's overall purpose in 1-2 sentences:\n{code}"
    )
    
    processed_elements = []
    for element in elements:
        docs = generate_structured_docs(element["type"], element["code"], file_extension)
        processed_elements.append({
            **element,
            "docs": docs
        })
    
    #print(processed_elements)
    
    return {
        "file_path": file_path,
        "summary": file_summary.content,
        "elements": processed_elements
    }


def generate_structured_docs(element_type: str, code: str, file_extension: str) -> str:
    """Generates rich documentation with attributes, parameters, and examples"""
    
    if element_type == "class":
        prompt = f"""Analyze this {file_extension} class and extract:
        1. Class name
        2. All attributes with types
        3. All methods with signatures
        4. Example usage

        Class code:
        {code}

        Return ONLY the JSON code and nothing else like this:
        {{
            "class_name": "ClassName",
            "description": "Class purpose",
            "attributes": [
                {{"name": "attr1", "type": "str", "description": "..."}}
            ],
            "methods": [
                {{"name": "method1", "params": ["param1: type"], "description": "..."}}
            ],
            "example": "usage example code"
        }}"""
            
    elif element_type == "function":
        prompt = f"""Analyze this {file_extension} function and extract:
        1. Function name
        2. All parameters with types
        3. Return type
        4. Example usage

        Function code:
        {code}

        Return ONLY the JSON code and nothing else like this:
        {{
            "function_name": "function_name",
            "description": "Function purpose",
            "params": [
                {{"name": "param1", "type": "str", "default": "None", "description": "..."}}
            ],
            "returns": {{"type": "return_type", "description": "..."}},
            "example": "usage example code"
        }}"""
    
    response = llm.invoke(prompt)
    json_str = response.content.strip()
    if json_str.startswith('```json'):
        json_str = json_str[7:-3].strip()
    elif json_str.startswith('```'):
        json_str = json_str[3:-3].strip()

    data = json.loads(json_str)
    
    if element_type == "class":
        attrs_table = "\n".join(
            f"| `{attr['name']}` | `{attr.get('type', '')}` | {attr['description']} |"
            for attr in data.get("attributes", [])
        )

        methods_list = "\n".join(
            f"- `{method['name']}({', '.join(method['params'])})`: {method['description']}"
            for method in data.get("methods", [])
        )
        
        return CLASS_TEMPLATE.format(
            language="C++",
            class_name=data.get("class_name", "UnknownClass"),
            description=data.get("description", ""),
            attributes_table=attrs_table,
            methods_list=methods_list,
            example_usage=data.get("example", "# No example provided")
        )
        
    else:
        params_table = "\n".join(
            f"| `{param['name']}` | `{param.get('type', '')}` | `{param.get('default', '')}` | {param['description']} |"
            for param in data.get("params", [])
        )
        
        returns_table = f"| `{data['returns'].get('type', 'void')}` | {data['returns'].get('description', '')} |"
        
        return FUNCTION_TEMPLATE.format(
            language="C++",
            function_name=data.get("function_name", "unknown_function"),
            description=data.get("description", ""),
            params=", ".join(p.get('name', '') for p in data.get("params", [])),
            return_type=data['returns'].get('type', 'void'),
            params_table=params_table,
            returns_table=returns_table,
            example_usage=data.get("example", "# No example provided")
        )


@tool()
def summarize_code(code: str) -> str:
    '''
    Summarizes the given code with self-review for accuracy and completeness.
    
    Args:
        code: The code to summarize.
    '''
    tokens = tokenizer.encode(code)
    token_count = len(tokens)
    print(f"Token count: {token_count}")

    draft_prompt = PromptTemplate(
        input_variables=["code"],
        template="""You are creating a documentation for a codebase with your team. Your task is to look at this file
                    and analyze the code and create a comprehensive draft summary for your team including:
    1. Primary purpose
    2. Key functions/classes
    3. Important algorithms
    4. Input/output flow
    5. Error handling

    Code:
    {code}

    Draft Summary:"""
    )
    draft_chain = LLMChain(llm=llm, prompt=draft_prompt)
    draft_summary = draft_chain.run(code)

    review_prompt = PromptTemplate(
        input_variables=["code", "draft_summary"],
        template="""You are creating a documentation for a codebase with your team. Your task is to look at this review that 
                    your team made about the code and make improvements and check your teams ideas so that the documentatopn
                    is more accurate and complete:
1. Verify technical correctness
2. Check for missing components
3. Ensure clarity of explanations
4. Flag any ambiguous statements

Provide specific improvements to the summary.

Original Code:
{code}

Draft Summary:
{draft_summary}

Critical Review:"""
    )
    review_chain = LLMChain(llm=llm, prompt=review_prompt)
    review = review_chain.run({"code": code, "draft_summary": draft_summary})

    final_prompt = PromptTemplate(
        input_variables=["code", "draft_summary", "review"],
        template="""You are creating a documentation for a codebase with your team. Your task is to look at this file in the codebase
                    and make a documentation based on your teams draft summary and review feedback. Create a polished, professional code summary:
1. Incorporate review feedback
2. Maintain technical accuracy
3. Improve clarity and organization
4. Keep concise but comprehensive

Code:
{code}

Draft Summary:
{draft_summary}

Review Feedback:
{review}

Final Summary:"""
    )
    final_chain = LLMChain(llm=llm, prompt=final_prompt)
    return final_chain.run({"code": code, "draft_summary": draft_summary, "review": review})


@tool()
def generate_mermaid_diagram(code: str) -> str:
    '''
    Generates a Mermaid.js diagram with self-verification.
    '''
    draft_prompt = PromptTemplate(
        input_variables=["code"],
        template="""You are creating a documentation for a codebase with your team. Your task is to
                    analyze this code and draft a Mermaid diagram covering:
1. Main components
2. Data/control flow
3. Key relationships
4. Important states

Return ONLY the Mermaid code.

Code:
{code}

Draft Diagram:"""
    )
    draft_chain = LLMChain(llm=llm, prompt=draft_prompt)
    draft_diagram = draft_chain.run(code)

    review_prompt = PromptTemplate(
        input_variables=["code", "draft_diagram"],
        template="""You are creating a documentation for a codebase with your team. Your task is to
                    analyze this mermaid code and verify this Mermaid diagram:
1. Check component completeness
2. Validate relationships
3. Confirm flow accuracy
4. Suggest improvements

Code:
{code}

Draft Diagram:
{draft_diagram}

Diagram Review:"""
    )
    review_chain = LLMChain(llm=llm, prompt=review_prompt)
    review = review_chain.run({"code": code, "draft_diagram": draft_diagram})

    final_prompt = PromptTemplate(
        input_variables=["code", "draft_diagram", "review"],
        template="""You are creating a documentation for a codebase with your team. Your team made a mermaid code draft and a review
                    to the draft, your job is to combine these and generate the mermaid diagram for the documentation:
1. Review feedback
2. Complete representation
3. Clear relationships
4. Optimal layout

Return ONLY the Mermaid code.

Code:
{code}

Draft Diagram:
{draft_diagram}

Review:
{review}

Final Diagram:"""
    )
    final_chain = LLMChain(llm=llm, prompt=final_prompt)
    final_diagram = final_chain.run({"code": code, "draft_diagram": draft_diagram, "review": review})
    
    if final_diagram.startswith("```mermaid"):
        final_diagram = final_diagram[10:-3].strip()
    elif final_diagram.startswith("```"):
        final_diagram = final_diagram[3:-3].strip()
    
    return final_diagram


@tool()
def create_markdown_documentation(summaries: list, diagrams: list, output_file: str) -> str:
    '''
    Creates a Markdown documentation file with summaries and Mermaid diagrams.
    
    Args:
        summaries: List of dictionaries with 'file_path' and 'summary'
        diagrams: List of Mermaid diagram codes
        output_file: Path to save the Markdown file
    '''
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as md_file:
        md_file.write("# Codebase Documentation\n\n")
        
        for file_docs in summaries:
            md_file.write(f"## `{file_docs['file_path']}`\n\n")
            md_file.write(f"**Summary**: {file_docs['summary']}\n\n")
            
            for element in file_docs['elements']:
                if element['type'] in ('class', 'function'):
                    md_file.write(element['docs'] + "\n\n")
            
            md_file.write("---\n\n")
    
    return f"Markdown documentation created at {output_file}"


@tool()
def process_repo(clone_dir: str, output_dir: str) -> str:
    '''
    Processes a repository file by file, generates documentation in Markdown format
    with embedded Mermaid diagrams.
    '''
    files = split_repo.invoke({"clone_dir": clone_dir})
    summaries = []
    diagrams = []
    
    os.makedirs(output_dir, exist_ok=True)
    
    for file in files:
        file_path = file['file_path']
        file_content = file['content']
        print(f"Processing file: {file_path}")
        
        summary = summarize_code.invoke({"code": file_content})
        summaries.append({"file_path": file_path, "summary": summary})
        
        mermaid_code = generate_mermaid_diagram.invoke({"code": file_content})
        diagrams.append(mermaid_code if mermaid_code else "")

    md_path = os.path.join(output_dir, "DOCUMENTATION.md")
    create_markdown_documentation.invoke({
        "summaries": summaries,
        "diagrams": diagrams,
        "output_file": md_path
    })
    
    return f"Processed {len(files)} files. Documentation written to {output_dir}"


@tool()
def process_repo2(clone_dir: str, output_dir: str) -> str:
    '''
    Processes a repository file by file, generates documentation in Markdown format
    with embedded Mermaid diagrams.
    '''
    files = split_repo.invoke({"clone_dir": clone_dir})
    all_docs = []
    
    for file in files:
        processed = process_file(file['file_path'], file['content'])
        all_docs.append(processed)

    create_markdown_documentation.invoke({
        "summaries": all_docs,
        "diagrams": [],
        "output_file": os.path.join(output_dir, "DOCUMENTATION.md")
    })
    return f"Processed {len(all_docs)} files"