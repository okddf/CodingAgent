from llm import llm
from typing import List, Dict
from tree_sitter import Language, Parser
import tree_sitter_python as tspython

PYTHON_LANGUAGE = Language(tspython.language())
parser = Parser(PYTHON_LANGUAGE)

def extract_elements_with_parser(code: str) -> List[Dict]:
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
    
    for element in elements:
        print(element["code"])
    return elements


def extract_elements_with_llm(code: str, file_extension: str) -> List[Dict]:
    """
    Extract classes and functions using llm.
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

    elements = []
    current_element = {}
    
    for line in response.split('\n'):
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