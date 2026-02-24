import os
import tree_sitter_python as tspy
import tree_sitter_java as tsjava         
import tree_sitter_javascript as tsjs    
from tree_sitter import Language, Parser, QueryCursor
from typing import List

# questa classe è una specie di contenitore di dati che rappresenta funzioni, classi o altro
class CodeNode:

    def __init__(
        self,
        name: str,           
        type: str,           
        content: str,        
        start_line: int,     
        end_line: int,       
        calls: List[str] = None  
    ):
        self.name = name
        self.type = type
        self.content = content
        self.start_line = start_line
        self.end_line = end_line

        # creiamo una nuova lista vuota per ogni nodo
        self.calls = calls if calls is not None else []


# questa classe analizza il file
class CodeGraphParser:

    def __init__(self):
        #mappa dei linguaggi supportati e le loro Query specifiche
        self.lang_configs = {
            "python": {
                "lib": tspy.language(),
                "query": """
                    (class_definition name: (identifier) @class.def)
                    (function_definition name: (identifier) @func.def)
                    (call function: (identifier) @func.call)
                    (call function: (attribute attribute: (identifier) @func.call))
                    (import_from_statement) @import.def
                    (import_statement) @import.def
                    (comment) @comment.text
                    (decorated_definition) @api.endpoint
                """
            },
            "java": {
                "lib": tsjava.language(),
                "query": """
                    (class_declaration name: (identifier) @class.def)
                    (method_declaration name: (identifier) @func.def)
                    (method_invocation name: (identifier) @func.call)
                    (import_declaration) @import.def
                    (line_comment) @comment.text
                    (block_comment) @comment.text
                   
                    (modifiers (annotation name: (identifier) @anno_name 
                        (#match? @anno_name "GetMapping|PostMapping|RequestMapping|PutMapping|DeleteMapping"))) @api.endpoint
                """
            },
            "javascript": {
                "lib": tsjs.language(),
                "query": """
                    (function_declaration name: (identifier) @func.def)
                    (method_definition name: (property_identifier) @func.def)
                    (call_expression function: (identifier) @func.call)
                    (import_statement) @import.def
                    (comment) @comment.text
                    
                    (call_expression 
                        function: (member_expression 
                            property: (property_identifier) @method_name
                            (#match? @method_name "get|post|put|delete|patch|use"))) @api.endpoint
                """
            }
        }

    #capire il linguaggio automaticamente
    def _detect_language(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        mapping = {
            ".py": "python",
            ".java": "java",
            ".js": "javascript"
        }
        lang = mapping.get(ext)
        if not lang:
            raise ValueError(f"linguaggio non supportato per l'estensione: {ext}")
        return lang


    def parse_file(self, file_path: str) -> List[CodeNode]:

        #capisce il linguaggio automaticamente e carica la configurazione
        lang_name = self._detect_language(file_path)
        config = self.lang_configs[lang_name]

        #specifichiamo che vogliamo analizzare il linguaggio capito dal file
        language = Language(config["lib"])
        parser = Parser(language)

        # la Query è come un filtro
        # cerchiamo definizioni di funzioni/classi e dove vengono fatte chiamate
        # @class.def e @func.call sono etichette che mettiamo ai pezzi trovati
        query_text = config["query"]

        # compiliamo la query
        # query() trasforma il testo della query in un oggetto Query
        query = language.query(query_text)

        # leggiamo il file come testo
        with open(file_path, "r", encoding="utf8") as f:
            source_code = f.read()

        # tree-sitter lavora con i byte, quindi convertiamo il testo
        source_bytes = source_code.encode("utf8")

        # il parser trasforma il file in un albero AST
        tree = parser.parse(source_bytes)

        # il Cursore è come un puntatore che scorre l'albero cercando i nostri filtri
        cursor = QueryCursor(query)

        # cerchiamo i match partendo dalla radice (tree.root_node)
        captures_dict = cursor.captures(tree.root_node)

        nodes: List[CodeNode] = []
        flat_captures = []

        # il dizionario restituito è diviso per etichette. lo appiattiamo in una lista
        # per poter ordinare tutto cronologicamente (come appare nel file)
        for tag, node_list in captures_dict.items():
            for node in node_list:
                flat_captures.append((node, tag))

        # ordiniamo i pezzi in base a dove appaiono (start_byte)
        # così sappiamo che se troviamo una chiamata, appartiene all'ultima funzione letta.
        flat_captures.sort(key=lambda x: x[0].start_byte)


        # processiamo ogni pezzo trovato
        for node, tag in flat_captures:

            # estraiamo il nome del nodo (per esempio il nome della funzione) dai byte originali
            name = source_bytes[node.start_byte:node.end_byte].decode("utf8")


            # se troviamo l'inizio di una funzione o classe
            if "class.def" in tag or "func.def" in tag:

                # node è solo il nome. node.parent è l'intero blocco (testa e corpo)
                full_node = node.parent

                # estraiamo tutto il testo contenuto tra l'inizio e la fine del blocco
                content = source_bytes[
                    full_node.start_byte:full_node.end_byte
                ].decode("utf8")


                # creiamo l oggetto CodeNode con le info complete
                nodes.append(
                    CodeNode(
                        name=name,
                        type="function" if "func" in tag else "class",

                        content=content,

                        # Aggiungiamo 1 perché Tree-sitter conta da 0, gli umani da 1
                        start_line=full_node.start_point[0] + 1,
                        end_line=full_node.end_point[0] + 1,
                    )
                )


            # se troviamo una chiamata a una funzione (per esempio print() o calcola())
            elif tag == "func.call":

                # se abbiamo già trovato almeno una funzione, e quindi nodes non è vuota,
                # aggiungiamo questa chiamata alla lista calls dell'ultima funzione creata
                if nodes:
                    # aggiungiamo la chiamata solo se l'ultimo nodo è una funzione o classe
                    if nodes[-1].type in ["function", "class", "api_endpoint"]:
                        nodes[-1].calls.append(name)

            # se troviamo un import (librerie esterne)
            elif tag == "import.def":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                nodes.append(CodeNode(name=name, type="import", content=content, 
                                     start_line=node.start_point[0]+1, end_line=node.end_point[0]+1))

            # se troviamo un commento
            elif tag == "comment.text":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                nodes.append(CodeNode(name="Comment", type="comment", content=content, 
                                     start_line=node.start_point[0]+1, end_line=node.end_point[0]+1))

            # se troviamo un endpoint API (decoratori in Python)
            elif tag == "api.endpoint":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                nodes.append(CodeNode(name="API_Route", type="api_endpoint", content=content, 
                                     start_line=node.start_point[0]+1, end_line=node.end_point[0]+1))

        return nodes