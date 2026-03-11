import os
import tree_sitter_python as tspy
import tree_sitter_java as tsjava         
import tree_sitter_javascript as tsjs    
from tree_sitter import Language, Parser, QueryCursor
from typing import List

# questa classe è una specie di contenitore di dati che rappresenta funzioni, classi o altro
# ci serve per tenere ordinate le informazioni di ogni pezzo di codice che troviamo
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
        self.name = name # il nome della funzione o classe
        self.type = type # se è una funzione, una classe o uno script
        self.content = content # il codice vero e proprio contenuto nel blocco
        self.start_line = start_line # dove inizia nel file
        self.end_line = end_line # dove finisce

        # creiamo una nuova lista vuota per ogni nodo per salvare quali altre funzioni chiama
        self.calls = calls if calls is not None else []


# questa classe analizza il file usando tree-sitter
#il parser è quello che apre i file scaricati dal corriere e inizia a leggerli
# li analizza riga per riga per capire la grammatica del codice
class CodeGraphParser:
    def __init__(self):
        # mappa dei linguaggi supportati e le loro query specifiche
        # le query servono a dire al parser: "cerca esattamente dove iniziano le funzioni"
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

    # capisce il linguaggio guardando l'estensione del file
    def _detect_language(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        mapping = {
            ".py": "python",
            ".java": "java",
            ".js": "javascript"
        }
        lang = mapping.get(ext)
        if not lang:
            # se non è tra quelli previsti, lanciamo un errore
            raise ValueError(f"linguaggio non supportato per l'estensione: {ext}")
        return lang


    def parse_file(self, file_path: str) -> List[CodeNode]:
        # capisce il linguaggio automaticamente e carica la configurazione corretta
        lang_name = self._detect_language(file_path)
        config = self.lang_configs[lang_name]

        # specifichiamo che vogliamo analizzare il linguaggio capito dal file
        language = Language(config["lib"])
        parser = Parser(language)

        # la query è come un filtro che estrae solo le parti che ci interessano (es. def nome():)
        query_text = config["query"]

        # compiliamo la query per renderla veloce
        query = language.query(query_text)

        # leggiamo il file originale come testo
        with open(file_path, "r", encoding="utf8") as f:
            source_code = f.read()

        # tree-sitter lavora con i byte, quindi convertiamo il testo in byte utf8
        source_bytes = source_code.encode("utf8")

        # il parser trasforma il testo piatto in un albero ast (abstract syntax tree)
        # un ast è una struttura gerarchica che rappresenta la logica del codice
        tree = parser.parse(source_bytes)

        # il cursore è come un puntatore che scorre l'albero cercando i nostri filtri
        cursor = QueryCursor(query)

        # cerchiamo i match partendo dalla radice dell'albero
        captures_dict = cursor.captures(tree.root_node)

        nodes: List[CodeNode] = []
        flat_captures = []

        # appiattiamo i risultati in una lista semplice per poterli ordinare
        for tag, node_list in captures_dict.items():
            for node in node_list:
                flat_captures.append((node, tag))

        # ordiniamo i pezzi in base a dove appaiono nel file (start_byte)
        # così le chiamate a funzione finiscono sotto la funzione che le contiene
        flat_captures.sort(key=lambda x: x[0].start_byte)

        # processiamo ogni pezzo trovato
        for node, tag in flat_captures:
            # estraiamo il nome del nodo (tipo il nome della funzione) dai byte originali
            name = source_bytes[node.start_byte:node.end_byte].decode("utf8")

            # se troviamo l'inizio di una funzione o classe
            if "class.def" in tag or "func.def" in tag:
                # node è solo il nome. node.parent è l'intero blocco (testa e corpo della funzione)
                full_node = node.parent

                # estraiamo tutto il testo contenuto tra l'inizio e la fine del blocco
                content = source_bytes[
                    full_node.start_byte:full_node.end_byte
                ].decode("utf8")

                # --- limitatore di contesto ---
                # se una funzione è gigante (più di 4000 caratteri) la tagliamo
                # altrimenti l'ai si confonde o finisce la memoria del prompt
                """inviare file troppo grandi causerebbe il superamento del limite di contesto di ollama, 
                rendendo l'ai confusa o incapace di rispondere. 
                per risolvere il problema alla radice, il sistema usa il grafo: invece di leggere un file enorme, 
                l'ai può navigare tra diverse funzioni collegate. 
                comunque, 4000 caratteri coprono solitamente la parte più importante di una funzione;"""
                if len(content) > 4000:
                    content = content[:4000] + "\n... [codice troncato per limiti di contesto] ..."

                # creiamo l'oggetto codenode con le info complete
                nodes.append(
                    CodeNode(
                        name=name,
                        type="class" if "class" in tag else "function",
                        content=content,
                        start_line=full_node.start_point[0] + 1,
                        end_line=full_node.end_point[0] + 1,
                    )
                )

            # se troviamo una chiamata a una funzione (per esempio print() o calcola())
            elif tag == "func.call":
                if nodes:
                    # aggiungiamo il nome della funzione chiamata all'ultima funzione analizzata
                    if nodes[-1].type in ["function", "class", "api_endpoint"]:
                        nodes[-1].calls.append(name)

            # se troviamo un import 
            elif tag == "import.def":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                nodes.append(CodeNode(name=name, type="import", content=content, 
                                     start_line=node.start_point[0]+1, end_line=node.end_point[0]+1))

            # se troviamo un commento lo salviamo, può servire all'ai per capire la logica
            elif tag == "comment.text":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                nodes.append(CodeNode(name="Comment", type="comment", content=content, 
                                     start_line=node.start_point[0]+1, end_line=node.end_point[0]+1))

            # se troviamo un endpoint api (utile per capire i punti di ingresso del software)
            elif tag == "api.endpoint":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                nodes.append(CodeNode(name="API_Route", type="api_endpoint", content=content, 
                                     start_line=node.start_point[0]+1, end_line=node.end_point[0]+1))

        # --- gestione script piatti (senza funzioni o classi) ---
        # se un file è solo una lista di comandi senza funzioni, tree-sitter non troverebbe nulla
        # quindi lo salviamo come entità intera di tipo 'script'
        significant_nodes = [n for n in nodes if n.type in ["function", "class", "api_endpoint"]]
        
        if not significant_nodes and len(source_code.strip()) > 0:
            # prendiamo il nome del file come nome dello script
            script_name = os.path.basename(file_path)
            content = source_code
            if len(content) > 4000:
                content = content[:4000] + "\n... [codice troncato per limiti di contesto] ..."
            
            nodes.append(
                CodeNode(
                    name=script_name,
                    type="script",
                    content=content,
                    start_line=1,
                    end_line=len(source_code.splitlines())
                )
            )

        return nodes