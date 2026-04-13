import os
import tree_sitter_python as tspy
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser, QueryCursor
from typing import List

class CodeNode:
    # questa classe è una specie di contenitore di dati che rappresenta funzioni, classi o altro
    # ci serve per tenere ordinate le informazioni di ogni pezzo di codice che troviamo
    def __init__(
        self,
        name: str,
        type: str,
        content: str,
        start_line: int,
        end_line: int,
        calls: List[str] = None,
        # NUOVO: classi da cui eredita (es. class Mio(Base): → base_classes = ["Base"])
        # serve per costruire le relazioni :inherits_from nel grafo e capire la gerarchia del progetto
        base_classes: List[str] = None,
        # NUOVO: decoratori applicati (es. @property, @app.route, @staticmethod)
        # utili per rilevare pattern architetturali (endpoint REST, metodi statici, ecc.)
        decorators: List[str] = None,
        # NUOVO: classifica gli import come 'internal' (relativi al progetto) o 'external' (librerie)
        # serve per capire le dipendenze critiche del progetto verso librerie esterne
        import_type: str = None,
    ):
        self.name = name # il nome della funzione o classe
        self.type = type # se è una funzione, una classe o uno script
        self.content = content # il codice vero e proprio contenuto nel blocco
        self.start_line = start_line # dove inizia nel file
        self.end_line = end_line # dove finisce

        # creiamo una nuova lista vuota per ogni nodo per salvare quali altre funzioni chiama
        self.calls = calls if calls is not None else []
        self.base_classes = base_classes if base_classes is not None else []
        self.decorators = decorators if decorators is not None else []
        self.import_type = import_type


# questa classe analizza il file usando tree-sitter
# il parser è quello che apre i file scaricati dal corriere e inizia a leggerli
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

        # librerie standard python: sono i moduli che fanno parte di python stesso
        # li usiamo per distinguere import interni/esterni dagli import di sistema
        # qualunque cosa non sia qui è considerata una dipendenza esterna (libreria installata)
        self._python_stdlib = {
            "os", "sys", "re", "json", "math", "time", "datetime", "pathlib",
            "typing", "collections", "itertools", "functools", "io", "abc",
            "logging", "unittest", "subprocess", "shutil", "glob", "copy",
            "random", "hashlib", "base64", "struct", "socket", "threading",
            "multiprocessing", "asyncio", "contextlib", "dataclasses", "enum",
            "string", "textwrap", "traceback", "warnings", "weakref", "gc",
            "inspect", "importlib", "pkgutil", "types", "operator", "heapq",
            "bisect", "array", "queue", "signal", "platform", "tempfile",
            "csv", "configparser", "argparse", "pprint", "http", "urllib",
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

    def _classify_python_import(self, import_content: str) -> str:
        """
        NUOVO: classifica un import python in tre categorie:
        - 'internal': import relativo al progetto corrente (from . import X  o  from .module import Y)
        - 'stdlib': modulo standard di python (os, sys, re, json, ecc.)
        - 'external': libreria di terze parti installata (numpy, fastapi, ollama, ecc.)
        questa distinzione è fondamentale per capire le dipendenze critiche del progetto
        """
        content = import_content.strip()

        # gli import relativi iniziano con 'from .' → sicuramente interni al progetto
        if content.startswith("from .") or content.startswith("from .."):
            return "internal"

        # estraiamo il nome del modulo radice (la prima parola dopo from o import)
        # es. "from numpy import array" → "numpy"
        # es. "import os.path" → "os"
        parts = content.split()
        if len(parts) >= 2:
            module_root = parts[1].split(".")[0].lower()
            if module_root in self._python_stdlib:
                return "stdlib"

        return "external"

    def _extract_python_base_classes(self, class_node, source_bytes: bytes) -> List[str]:
        """
        NUOVO: estrae le classi base da una class definition python.
        es. class MyService(BaseService, ABC): → ["BaseService", "ABC"]
        questo permette di costruire la gerarchia di ereditarietà nel grafo
        e di rilevare pattern come 'tutti i service ereditano da BaseService'
        """
        base_classes = []
        # scorriamo i figli del nodo class per trovare la lista di argomenti (superclassi)
        for child in class_node.children:
            # in python l'ast ha un nodo 'argument_list' per le classi base
            if child.type == "argument_list":
                for arg in child.children:
                    # prendiamo solo gli identifier e gli attributi (es. abc.ABC)
                    if arg.type in ("identifier", "attribute"):
                        base_classes.append(source_bytes[arg.start_byte:arg.end_byte].decode("utf8"))
        return base_classes

    def _extract_decorators(self, decorated_node, source_bytes: bytes) -> List[str]:
        """
        NUOVO: estrae i decoratori da un nodo decorated_definition.
        es. @app.route('/api/v1/query', methods=['GET'])  →  ["app.route"]
        i decoratori rivelano pattern architetturali importanti:
        - @app.route, @router.get → endpoint REST
        - @staticmethod, @classmethod → scelte di design
        - @pytest.mark.* → pattern di testing
        - @property → pattern di incapsulamento
        """
        decorators = []
        for child in decorated_node.children:
            if child.type == "decorator":
                # il testo del decoratore senza il simbolo '@'
                dec_text = source_bytes[child.start_byte:child.end_byte].decode("utf8").strip()
                dec_text = dec_text.lstrip("@").split("(")[0].strip()
                decorators.append(dec_text)
        return decorators

    def parse_file(self, file_path: str) -> List[CodeNode]:
        # capisce il linguaggio automaticamente e carica la configurazione corretta
        lang_name = self._detect_language(file_path)
        config = self.lang_configs[lang_name]

        # specifichiamo che vogliamo analizzare il linguaggio capito dal file
        language = Language(config["lib"])
        parser = Parser(language)

        # la query è come un filtro che estrae solo le parti che ci interessano (es. def blablabla():)
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
        # così le chiamate a funzione finiscono sotto la funzione stessa, e non possono apparire prima nella lista
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

                # nessun troncamento: il contenuto completo viene salvato nel grafo
                # l'embedder gestisce autonomamente il limite di token tramite num_ctx=8192

                # NUOVO: se è una classe, estraiamo le classi base per la gerarchia di ereditarietà
                base_classes = []
                if "class" in tag and lang_name == "python":
                    base_classes = self._extract_python_base_classes(full_node, source_bytes)

                # NUOVO: controlliamo se il nodo padre è un decorated_definition
                # in python, @decorator + def/class sono raggruppati in un nodo decorated_definition
                decorators = []
                if full_node.parent and full_node.parent.type == "decorated_definition":
                    decorators = self._extract_decorators(full_node.parent, source_bytes)

                # creiamo l'oggetto codenode con le info complete
                nodes.append(
                    CodeNode(
                        name=name,
                        type="class" if "class" in tag else "function",
                        content=content,
                        start_line=full_node.start_point[0] + 1,
                        end_line=full_node.end_point[0] + 1,
                        base_classes=base_classes,
                        decorators=decorators,
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

                # NUOVO: classifichiamo l'import per capire le dipendenze del progetto
                import_type = None
                if lang_name == "python":
                    import_type = self._classify_python_import(content)

                nodes.append(CodeNode(
                    name=name,
                    type="import",
                    content=content,
                    start_line=node.start_point[0]+1,
                    end_line=node.end_point[0]+1,
                    import_type=import_type,
                ))

            # se troviamo un commento lo salviamo, può servire all'ai per capire la logica
            elif tag == "comment.text":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                nodes.append(CodeNode(name="Comment", type="comment", content=content,
                                     start_line=node.start_point[0]+1, end_line=node.end_point[0]+1))

            # se troviamo un endpoint api (utile per capire i punti di ingresso del software)
            elif tag == "api.endpoint":
                content = source_bytes[node.start_byte:node.end_byte].decode("utf8")
                # NUOVO: estraiamo i decoratori anche dagli endpoint api
                decorators = self._extract_decorators(node, source_bytes) if lang_name == "python" else []
                nodes.append(CodeNode(
                    name="API_Route",
                    type="api_endpoint",
                    content=content,
                    start_line=node.start_point[0]+1,
                    end_line=node.end_point[0]+1,
                    decorators=decorators,
                ))

        # --- gestione script piatti (senza funzioni o classi) ---
        # se un file è solo una lista di comandi senza funzioni, tree-sitter non troverebbe nulla
        # quindi lo salviamo come entità intera di tipo 'script'
        significant_nodes = [n for n in nodes if n.type in ["function", "class", "api_endpoint"]]

        if not significant_nodes and len(source_code.strip()) > 0:
            # prendiamo il nome del file come nome dello script
            script_name = os.path.basename(file_path)
            content = source_code
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
