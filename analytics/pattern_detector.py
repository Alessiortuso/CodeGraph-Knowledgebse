# questo modulo è il cuore del rilevamento di pattern impliciti nel progetto
# il suo scopo è trovare regolarità nel codice che non sono dichiarate in nessun documento
# per esempio: "tutte le classi che finiscono in Service hanno le stesse dipendenze"
# oppure: "gli endpoint REST seguono sempre la stessa struttura di validazione"
# queste informazioni sono preziose per chi entra nel progetto e deve capire come funziona

import logging
from collections import Counter

logger = logging.getLogger(__name__)


class PatternDetector:
    """
    analizza il grafo di conoscenza per individuare:
    - pattern architetturali (Service, Repository, Controller, ecc.)
    - convenzioni di naming implicite (come vengono chiamate funzioni e classi)
    - librerie esterne ricorrenti (dipendenze critiche)
    - strutture ricorrenti (funzioni che tutti i file hanno in comune)
    - aree centrali del progetto (i file più connessi = i più critici)
    """

    def __init__(self, db_client):
        # salviamo il riferimento al client del database per eseguire le query cypher
        self.db = db_client

    def detect_naming_conventions(self, project_name) -> dict:
        """
        PATTERN 1: Convenzioni di naming
        analizza i nomi di classi e funzioni per capire se il progetto usa:
        - suffissi ricorrenti (Service, Manager, Helper, Handler, Controller, Repository)
        - prefissi ricorrenti (get_, set_, process_, handle_, create_)
        - stile generale (snake_case vs camelCase)
        questa è una delle convenzioni implicite più importanti da rilevare
        perché non è mai scritta da nessuna parte ma tutti la seguono
        """
        query = """
        MATCH (ce:CodeEntity {project: $project})
        WHERE ce.type IN ['class', 'function']
        RETURN ce.name AS name, ce.type AS type
        """
        results = self.db.execute_query(query, {"project": project_name})

        class_names = [r["name"] for r in results if r.get("type") == "class"]
        func_names = [r["name"] for r in results if r.get("type") == "function"]

        # --- rilevamento suffissi nei nomi delle classi ---
        # per esempio se molte classi finiscono in "Service" è un pattern architetturale chiaro
        common_class_suffixes = ["Service", "Manager", "Handler", "Repository", "Controller",
                                  "Helper", "Builder", "Factory", "Processor", "Client",
                                  "Analyzer", "Generator", "Validator", "Parser", "Loader"]
        suffix_counts = Counter()
        for name in class_names:
            for suffix in common_class_suffixes:
                if name.endswith(suffix):
                    suffix_counts[suffix] += 1

        # --- rilevamento prefissi nei nomi delle funzioni ---
        # per esempio get_, set_, process_, handle_ indicano convenzioni di naming delle funzioni
        common_func_prefixes = ["get_", "set_", "process_", "handle_", "create_", "update_",
                                 "delete_", "parse_", "build_", "run_", "execute_", "fetch_",
                                 "save_", "load_", "extract_", "compute_", "validate_", "check_"]
        prefix_counts = Counter()
        for name in func_names:
            for prefix in common_func_prefixes:
                if name.lower().startswith(prefix):
                    prefix_counts[prefix] += 1

        # --- rilevamento stile generale (snake_case vs camelCase) ---
        # contiamo quanti nomi hanno underscore (snake_case) vs maiuscole interne (camelCase)
        snake_case_count = sum(1 for n in func_names if "_" in n)
        camel_case_count = sum(1 for n in func_names if "_" not in n and any(c.isupper() for c in n[1:]))
        naming_style = "snake_case" if snake_case_count >= camel_case_count else "camelCase"

        return {
            "class_suffixes": dict(suffix_counts.most_common(5)),
            "function_prefixes": dict(prefix_counts.most_common(5)),
            "naming_style": naming_style,
            "total_classes": len(class_names),
            "total_functions": len(func_names),
        }

    def detect_architectural_patterns(self, project_name) -> list:
        """
        PATTERN 2: Pattern architetturali
        cerca strutture ricorrenti che indicano uno stile architetturale specifico.
        per esempio: se ci sono classi Service, Repository e Controller → pattern MVC/layered
        se ci sono molti decoratori @route → architettura REST API
        questi pattern rivelano come il team ha strutturato il codice senza documentarlo
        """
        patterns_found = []

        # query per contare i tipi di classi presenti
        query_classes = """
        MATCH (ce:CodeEntity {project: $project, type: 'class'})
        RETURN ce.name AS name, ce.decorators AS decorators, ce.base_classes AS base_classes
        """
        classes = self.db.execute_query(query_classes, {"project": project_name})

        class_names = [c["name"] for c in classes if c.get("name")]

        # --- Pattern Layered Architecture ---
        # presenza contemporanea di Service + Repository + Controller indica architettura a strati
        has_services = any(n.endswith("Service") for n in class_names)
        has_repositories = any(n.endswith("Repository") for n in class_names)
        has_controllers = any(n.endswith("Controller") for n in class_names)

        if has_services and has_repositories:
            patterns_found.append({
                "pattern": "Layered Architecture",
                "evidence": "Presenza di classi Service e Repository che separano logica e accesso ai dati",
                "confidence": "alta" if has_controllers else "media"
            })

        # --- Pattern REST API ---
        # contiamo gli endpoint rilevati (nodi di tipo api_endpoint)
        query_endpoints = """
        MATCH (ce:CodeEntity {project: $project, type: 'api_endpoint'})
        RETURN count(ce) AS count
        """
        endpoint_result = self.db.execute_query(query_endpoints, {"project": project_name})
        endpoint_count = endpoint_result[0]["count"] if endpoint_result else 0

        if endpoint_count > 0:
            patterns_found.append({
                "pattern": "REST API",
                "evidence": f"Rilevati {endpoint_count} endpoint API nel progetto",
                "confidence": "alta" if endpoint_count > 3 else "media"
            })

        # --- Pattern Singleton / Client unico ---
        # classi che finiscono in Client tendono ad essere usate come singleton
        client_classes = [n for n in class_names if n.endswith("Client")]
        if client_classes:
            patterns_found.append({
                "pattern": "Client Singleton",
                "evidence": f"Classi client rilevate: {', '.join(client_classes)}",
                "confidence": "media"
            })

        # --- Pattern Builder ---
        builder_classes = [n for n in class_names if n.endswith("Builder") or n.endswith("Factory")]
        if builder_classes:
            patterns_found.append({
                "pattern": "Builder/Factory",
                "evidence": f"Classi builder/factory rilevate: {', '.join(builder_classes)}",
                "confidence": "media"
            })

        return patterns_found

    def detect_external_dependencies(self, project_name) -> list:
        """
        PATTERN 3: Dipendenze esterne critiche
        raccoglie tutti gli import classificati come 'external' nel grafo
        e li conta per capire quali librerie esterne sono più usate.
        sapere che un progetto dipende criticamente da numpy, fastapi, ollama
        è un'informazione fondamentale per chi deve prendere in mano il progetto
        """
        query = """
        MATCH (ce:CodeEntity {project: $project, type: 'import'})
        WHERE ce.import_type = 'external'
        RETURN ce.content AS content
        """
        results = self.db.execute_query(query, {"project": project_name})

        # estraiamo il nome della libreria da ogni riga di import
        # es. "from numpy import array" → "numpy"
        # es. "import fastapi" → "fastapi"
        lib_counter = Counter()
        for r in results:
            content = r.get("content") or ""
            parts = content.strip().split()
            if len(parts) >= 2:
                # togliamo "from" o "import" e prendiamo il modulo radice
                module = parts[1].split(".")[0].lower()
                # filtriamo i moduli vuoti o troppo corti
                if len(module) > 1:
                    lib_counter[module] += 1

        return [{"library": lib, "usage_count": count}
                for lib, count in lib_counter.most_common(10)]

    def detect_central_components(self, project_name) -> list:
        """
        PATTERN 4: Componenti centrali (high connectivity)
        trova i file e le funzioni che sono più connessi nel grafo:
        più un nodo ha relazioni :calls, :has_method, :contains_entity
        più è centrale nell'architettura del progetto.
        questi sono i componenti più critici: se cambiano, cambiano molte cose.
        utile per chi entra nel progetto a capire dove sta il cuore del sistema
        """
        query = """
        MATCH (f:File {project: $project})
        OPTIONAL MATCH (f)-[:contains_entity]->(ce:CodeEntity)
        OPTIONAL MATCH (ce)-[:calls]->(called:CodeEntity)
        WITH f, count(distinct ce) AS entity_count, count(distinct called) AS outgoing_calls
        WHERE entity_count > 0
        RETURN f.name AS file, f.path AS path,
               entity_count AS entities,
               outgoing_calls AS dependencies
        ORDER BY (entity_count + outgoing_calls) DESC
        LIMIT 10
        """
        return self.db.execute_query(query, {"project": project_name})

    def detect_inheritance_chains(self, project_name) -> list:
        """
        PATTERN 5: Catene di ereditarietà
        trova le classi che ereditano da altre classi nel progetto.
        questo rivela la gerarchia di astrazione e i pattern OOP usati dal team.
        per esempio: tutti i processor ereditano da BaseProcessor → pattern template method
        """
        query = """
        MATCH (child:CodeEntity {project: $project, type: 'class'})
        WHERE child.base_classes IS NOT NULL AND size(child.base_classes) > 0
        RETURN child.name AS class_name,
               child.base_classes AS inherits_from,
               child.file AS file
        """
        return self.db.execute_query(query, {"project": project_name})

    def run_full_detection(self, project_name) -> dict:
        """
        esegue tutte le analisi di pattern detection e restituisce un report completo.
        questo report viene usato dal sintetizzatore per arricchire le risposte
        e dall'onboarding report per fornire una panoramica al nuovo membro del team
        """
        logger.info(f"[pattern detector] avvio analisi pattern per progetto: {project_name}")

        naming = self.detect_naming_conventions(project_name)
        arch_patterns = self.detect_architectural_patterns(project_name)
        dependencies = self.detect_external_dependencies(project_name)
        central = self.detect_central_components(project_name)
        inheritance = self.detect_inheritance_chains(project_name)

        logger.info(f"[pattern detector] trovati {len(arch_patterns)} pattern architetturali")
        logger.info(f"[pattern detector] trovate {len(dependencies)} dipendenze esterne")

        return {
            "naming_conventions": naming,
            "architectural_patterns": arch_patterns,
            "external_dependencies": dependencies,
            "central_components": central,
            "inheritance_chains": inheritance,
        }
