import os
from ingestion.parser.code_parser import CodeGraphParser

def run_analysis():
    # 1. Inizializziamo il parser automatico
    v_parser = CodeGraphParser()
    
    # Usiamo un file Python per questo test completo
    test_filename = "test_completo.py"
    
    # 2. Creazione di un file di test con TUTTI gli elementi (API, Import, Commenti)
    print(f"📝 Preparazione file di test: {test_filename}...")
    codice_test = """
import math
import os

# Questa funzione calcola l'area di un cerchio
def calcola_area(raggio):
    return math.pi * (raggio ** 2)

@app.get("/api/area")
def api_calcola_area():
    risultato = calcola_area(10)
    print(f"Risultato: {risultato}")
"""
    
    with open(test_filename, "w", encoding="utf-8") as f:
        f.write(codice_test)

    print(f"🚀 Analisi in corso su {test_filename}...")
    
    try:
        # 3. Eseguiamo il parsing
        nodes = v_parser.parse_file(test_filename)
        
        # 4. Stampiamo i risultati divisi per tipologia
        print(f"\n✅ Analisi completata! Risultati trovati:")
        print("="*50)
        
        for n in nodes:
            # Usiamo delle icone diverse per distinguere i tipi
            icona = "📦" if n.type == "import" else \
                    "💬" if n.type == "comment" else \
                    "🌐" if n.type == "api_endpoint" else \
                    "⚙️" if n.type == "function" else "📁"
            
            print(f"{icona} [{n.type.upper()}] Nome: {n.name}")
            print(f"   📍 Linee: {n.start_line}-{n.end_line}")
            
            if n.calls:
                print(f"   🔗 Chiama: {list(set(n.calls))}")
            
            # Mostriamo la prima riga del contenuto
            anteprima = n.content.splitlines()[0][:50]
            print(f"   💻 Codice: {anteprima}...")
            print("-" * 30)

    except Exception as e:
        print(f"❌ Errore durante l'analisi: {e}")

if __name__ == "__main__":
    run_analysis()