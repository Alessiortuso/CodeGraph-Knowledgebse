import os
from ingestion.parser import CodeGraphParser

def run_analysis():
    v_parser = CodeGraphParser()
    test_filename = "test_completo.py"
    
    print(f"PREPARAZIONE FILE DI TEST: {test_filename}...")
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

    print(f"ANALISI IN CORSO SU {test_filename}...")
    
    try:
        nodes = v_parser.parse_file(test_filename)

        print(f"\nANALISI COMPLETATA - RISULTATI:")
        print("="*50)
        
        for n in nodes:
            tipo_label = n.type.upper()
            
            print(f"TIPO: [{tipo_label}] Nome: {n.name}")
            print(f"  Linee: {n.start_line}-{n.end_line}")
            
            if n.calls:
                print(f"  Chiama: {list(set(n.calls))}")
            
            anteprima = n.content.splitlines()[0][:50] if n.content else "N/A"
            print(f"  Codice: {anteprima}...")
            print("-" * 30)

    except Exception as e:
        print(f"ERRORE DURANTE L'ANALISI: {e}")

if __name__ == "__main__":
    run_analysis()