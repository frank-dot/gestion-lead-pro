import sqlite3
import pandas as pd
from datetime import datetime

def init_database():
    """Crée toutes les tables nécessaires pour la gestion SDA"""
    
    conn = sqlite3.connect('sda_database.db')
    cursor = conn.cursor()
    
    # Table des prestataires/fournisseurs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prestataires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT UNIQUE,
            contact TEXT,
            telephone TEXT,
            email TEXT,
            contrat TEXT,
            date_attribution DATE,
            actif BOOLEAN DEFAULT 1,
            date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table principale des numéros SDA
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS numeros_sda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT UNIQUE,
            prestataire_id INTEGER,
            type_ligne TEXT,
            date_attribution DATE,
            statut TEXT DEFAULT 'actif',
            derniere_verification TIMESTAMP,
            danger_percentage INTEGER DEFAULT 0,
            niveau_danger TEXT,
            commentaires TEXT,
            FOREIGN KEY (prestataire_id) REFERENCES prestataires (id)
        )
    ''')
    
    # Table d'historique des vérifications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historique_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_id INTEGER,
            date_verification TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            danger_percentage INTEGER,
            niveau_danger TEXT,
            commentaires TEXT,
            source TEXT,
            FOREIGN KEY (numero_id) REFERENCES numeros_sda (id)
        )
    ''')
    
    # Table de configuration des alertes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config_alertes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_alerte TEXT,
            destinataires TEXT,
            smtp_server TEXT,
            smtp_port INTEGER,
            email_expediteur TEXT,
            password TEXT,
            actif BOOLEAN DEFAULT 1
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Base de données initialisée avec succès")

def verifier_et_mettre_a_jour(self, numero_id, numero):
    """Vérifie un numéro et met à jour la base avec les résultats"""
    
    # Utiliser ton ReputationChecker existant
    from reputation_checker import ReputationChecker
    checker = ReputationChecker()
    
    # Lancer la vérification
    resultat = checker.analyze_number(numero)
    
    # Extraire les infos de Numeroinconnu
    ni = resultat.get('numeroinconnu', {})
    danger_pct = ni.get('danger_percentage', 0)
    
    # Déterminer le niveau de danger
    if danger_pct >= 70:
        niveau = "🔴 Dangereux"
    elif danger_pct >= 50:
        niveau = "🟠 Gênant"
    elif danger_pct > 0:
        niveau = "🟢 Peu risqué"
    else:
        niveau = "⚪ Inconnu"
    
    # Mettre à jour la base
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE numeros_sda 
        SET derniere_verification = ?,
            danger_percentage = ?,
            niveau_danger = ?,
            commentaires = ?
        WHERE id = ?
    ''', (datetime.now(), danger_pct, niveau, str(resultat.get('comments', [])), numero_id))
    
    # Ajouter à l'historique
    cursor.execute('''
        INSERT INTO historique_verifications 
        (numero_id, danger_percentage, niveau_danger, commentaires, source)
        VALUES (?, ?, ?, ?, ?)
    ''', (numero_id, danger_pct, niveau, str(resultat.get('comments', [])), 'verification_manuelle'))
    
    conn.commit()
    conn.close()
    
    return resultat

def verifier_lot(self, prestataire_nom=None, limite=50):
    """Vérifie un lot de numéros non vérifiés récemment"""
    
    conn = sqlite3.connect(self.db_path)
    
    # Récupérer les numéros à vérifier
    if prestataire_nom:
        query = '''
            SELECT n.id, n.numero 
            FROM numeros_sda n
            JOIN prestataires p ON n.prestataire_id = p.id
            WHERE p.nom = ? 
            AND (n.derniere_verification IS NULL 
                 OR n.derniere_verification < date('now', '-7 days'))
            LIMIT ?
        '''
        numeros = pd.read_sql(query, conn, params=[prestataire_nom, limite])
    else:
        query = '''
            SELECT id, numero FROM numeros_sda 
            WHERE derniere_verification IS NULL 
               OR derniere_verification < date('now', '-7 days')
            LIMIT ?
        '''
        numeros = pd.read_sql(query, conn, params=[limite])
    
    conn.close()
    
    if len(numeros) == 0:
        return {"message": "✅ Tous les numéros sont à jour", "verifies": 0}
    
    # Vérifier chaque numéro
    resultats = []
    for _, row in numeros.iterrows():
        print(f"🔍 Vérification du numéro {row['numero']}...")
        resultat = self.verifier_et_mettre_a_jour(row['id'], row['numero'])
        resultats.append(resultat)
    
    return {
        "message": f"✅ {len(numeros)} numéros vérifiés",
        "verifies": len(numeros),
        "details": resultats
    }