import sqlite3
import pandas as pd
from datetime import datetime
import time
import json

class SDAManager:
    def __init__(self, db_path='sda_database.db'):
        self.db_path = db_path
    
    def ajouter_prestataire(self, nom, contact=None, telephone=None, email=None):
        """Ajoute un nouveau prestataire"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO prestataires (nom, contact, telephone, email, date_attribution)
                VALUES (?, ?, ?, ?, ?)
            ''', (nom, contact, telephone, email, datetime.now().date()))
            
            conn.commit()
            prestataire_id = cursor.lastrowid
            print(f"✅ Prestataire '{nom}' ajouté avec l'ID {prestataire_id}")
            return prestataire_id
            
        except sqlite3.IntegrityError:
            print(f"⚠️ Le prestataire '{nom}' existe déjà")
            # Récupérer l'ID existant
            cursor.execute("SELECT id FROM prestataires WHERE nom = ?", (nom,))
            return cursor.fetchone()[0]
        finally:
            conn.close()
    
    def importer_numeros(self, fichier, prestataire_nom, colonne_numero='numero'):
        """Importe des numéros depuis un fichier CSV/Excel"""
        
        # 1. Vérifier que le fichier n'est pas vide
        if fichier.size == 0:
            return {
                'total_fichier': 0,
                'importes': 0,
                'prestataire': prestataire_nom,
                'erreur': "Le fichier est vide"
            }
        
        # 2. Lire le fichier
        try:
            if fichier.name.endswith('.csv'):
                # Essayer différents encodages pour les CSV
                encodages = ['utf-8', 'latin1', 'cp1252']
                df = None
                
                for enc in encodages:
                    try:
                        fichier.seek(0)
                        df = pd.read_csv(fichier, encoding=enc)
                        break
                    except:
                        continue
                
                if df is None:
                    return {
                        'total_fichier': 0,
                        'importes': 0,
                        'prestataire': prestataire_nom,
                        'erreur': "Impossible de lire le CSV (encodage non reconnu)"
                    }
            else:
                # Fichier Excel
                fichier.seek(0)
                df = pd.read_excel(fichier)
                
        except pd.errors.EmptyDataError:
            return {
                'total_fichier': 0,
                'importes': 0,
                'prestataire': prestataire_nom,
                'erreur': "Fichier vide"
            }
        except Exception as e:
            return {
                'total_fichier': 0,
                'importes': 0,
                'prestataire': prestataire_nom,
                'erreur': str(e)
            }
        
        # 3. Vérifier que le DataFrame contient des données
        if df.empty:
            return {
                'total_fichier': 0,
                'importes': 0,
                'prestataire': prestataire_nom,
                'erreur': "Le fichier ne contient aucune donnée"
            }
        
        # 4. Nettoyer les numéros
        if colonne_numero in df.columns:
            df[colonne_numero] = df[colonne_numero].astype(str).str.replace(r'[\s\-\(\)]', '', regex=True)
        else:
            # Si la colonne n'existe pas, prendre la première colonne
            df[df.columns[0]] = df[df.columns[0]].astype(str).str.replace(r'[\s\-\(\)]', '', regex=True)
            colonne_numero = df.columns[0]
        
        # 5. Récupérer l'ID du prestataire
        prestataire_id = self.ajouter_prestataire(prestataire_nom)
        
        # 6. Importer dans la base
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        numeros_importes = 0
        for _, row in df.iterrows():
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO numeros_sda 
                    (numero, prestataire_id, date_attribution)
                    VALUES (?, ?, ?)
                ''', (str(row[colonne_numero]), prestataire_id, datetime.now().date()))
                if cursor.rowcount == 1:
                    numeros_importes += 1
            except Exception as e:
                print(f"Erreur sur {row[colonne_numero]}: {e}")
        
        conn.commit()
        conn.close()
    
        return {
            'total_fichier': len(df),
            'importes': numeros_importes,
            'prestataire': prestataire_nom,
            'erreur': None
        }
    
    def get_numeros_par_prestataire(self, prestataire_nom=None):
        """Récupère les numéros filtrés par prestataire"""
        conn = sqlite3.connect(self.db_path)
        
        if prestataire_nom:
            query = '''
                SELECT n.*, p.nom as prestataire_nom 
                FROM numeros_sda n
                JOIN prestataires p ON n.prestataire_id = p.id
                WHERE p.nom = ?
            '''
            df = pd.read_sql(query, conn, params=[prestataire_nom])
        else:
            query = '''
                SELECT n.*, p.nom as prestataire_nom 
                FROM numeros_sda n
                JOIN prestataires p ON n.prestataire_id = p.id
            '''
            df = pd.read_sql(query, conn)
        
        conn.close()
        return df
    
    def get_statistiques_globales(self):
        """Retourne les statistiques pour le tableau de bord"""
        conn = sqlite3.connect(self.db_path)
        
        stats = {}
        
        # Total numéros
        stats['total'] = pd.read_sql("SELECT COUNT(*) as count FROM numeros_sda", conn).iloc[0]['count']
        
        # Numéros vérifiés
        stats['verifies'] = pd.read_sql(
            "SELECT COUNT(*) as count FROM numeros_sda WHERE derniere_verification IS NOT NULL", 
            conn
        ).iloc[0]['count']
        
        # Numéros spammés (danger >= 50)
        stats['spams'] = pd.read_sql(
            "SELECT COUNT(*) as count FROM numeros_sda WHERE danger_percentage >= 50", 
            conn
        ).iloc[0]['count']

        # Vérifications en échec technique (source indisponible/bloquée/réseau)
        stats['echecs'] = pd.read_sql(
            "SELECT COUNT(*) as count FROM numeros_sda WHERE niveau_danger LIKE '❌%'", 
            conn
        ).iloc[0]['count']
        
        # Par prestataire
        stats['par_prestataire'] = pd.read_sql('''
            SELECT p.nom, 
                   COUNT(n.id) as total,
                   SUM(CASE WHEN n.danger_percentage >= 50 THEN 1 ELSE 0 END) as spams,
                   SUM(CASE WHEN n.niveau_danger LIKE '❌%' THEN 1 ELSE 0 END) as echecs
            FROM prestataires p
            LEFT JOIN numeros_sda n ON p.id = n.prestataire_id
            GROUP BY p.nom
        ''', conn)
        
        conn.close()
        
        stats['sains'] = max(0, stats['total'] - stats['spams'] - stats['echecs'])
        return stats
    
    def verifier_et_mettre_a_jour(self, numero_id, numero):
        """Vérifie un numéro et met à jour la base avec les résultats"""
        from reputation_checker import ReputationChecker
        checker = ReputationChecker()
        
        # Lancer la vérification
        resultat = checker.analyze_number(numero)
        
        # Extraire les infos de Numeroinconnu
        ni = resultat.get('numeroinconnu', {})
        danger_pct = ni.get('danger_percentage', 0)
        source_status = ni.get('source_status', 'unknown')
        error_message = ni.get('error')

        technical_fail_statuses = {'network_error', 'http_error', 'blocked', 'failed'}
        verification_failed = source_status in technical_fail_statuses
        
        # Déterminer le niveau de danger
        if verification_failed:
            niveau = "❌ Échec vérification"
            danger_pct = None
        elif danger_pct >= 70:
            niveau = "🔴 Dangereux"
        elif danger_pct >= 50:
            niveau = "🟠 Gênant"
        elif danger_pct > 0:
            niveau = "🟡 À surveiller"
        else:
            niveau = "⚪ Inconnu"

        comments_payload = {
            "source_status": source_status,
            "error": error_message,
            "confidence": resultat.get("confidence"),
            "reasons": resultat.get("reasons", []),
            "comments": resultat.get("comments", []),
        }
        
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
        ''', (datetime.now(), danger_pct, niveau, json.dumps(comments_payload, ensure_ascii=False), numero_id))
        
        # Ajouter à l'historique
        cursor.execute('''
            INSERT INTO historique_verifications 
            (numero_id, danger_percentage, niveau_danger, commentaires, source)
            VALUES (?, ?, ?, ?, ?)
        ''', (numero_id, danger_pct, niveau, json.dumps(comments_payload, ensure_ascii=False), 'verification_manuelle'))
        
        conn.commit()
        conn.close()
        
        return resultat

    def verifier_lot(self, prestataire_nom=None, limite=None, force=False):
        """
        Vérifie un lot de numéros
        Si limite = None, vérifie TOUS les numéros non vérifiés récemment
        """
        conn = sqlite3.connect(self.db_path)
        
        if prestataire_nom:
            if limite is not None:
                if force:
                    query = '''
                        SELECT n.id, n.numero 
                        FROM numeros_sda n
                        JOIN prestataires p ON n.prestataire_id = p.id
                        WHERE p.nom = ?
                        LIMIT ?
                    '''
                    numeros = pd.read_sql(query, conn, params=[prestataire_nom, limite])
                else:
                    query = '''
                        SELECT n.id, n.numero 
                        FROM numeros_sda n
                        JOIN prestataires p ON n.prestataire_id = p.id
                        WHERE p.nom = ? 
                        AND (n.derniere_verification IS NULL 
                            OR n.derniere_verification < date('now', '-7 days')
                            OR n.niveau_danger LIKE '❌%')
                        LIMIT ?
                    '''
                    numeros = pd.read_sql(query, conn, params=[prestataire_nom, limite])
            else:
                if force:
                    query = '''
                        SELECT n.id, n.numero 
                        FROM numeros_sda n
                        JOIN prestataires p ON n.prestataire_id = p.id
                        WHERE p.nom = ?
                    '''
                    numeros = pd.read_sql(query, conn, params=[prestataire_nom])
                else:
                    # 👇 TOUS les numéros du prestataire
                    query = '''
                        SELECT n.id, n.numero 
                        FROM numeros_sda n
                        JOIN prestataires p ON n.prestataire_id = p.id
                        WHERE p.nom = ? 
                        AND (n.derniere_verification IS NULL 
                            OR n.derniere_verification < date('now', '-7 days')
                            OR n.niveau_danger LIKE '❌%')
                    '''
                    numeros = pd.read_sql(query, conn, params=[prestataire_nom])
        else:
            if limite is not None:
                if force:
                    query = '''
                        SELECT id, numero FROM numeros_sda
                        LIMIT ?
                    '''
                    numeros = pd.read_sql(query, conn, params=[limite])
                else:
                    query = '''
                        SELECT id, numero FROM numeros_sda 
                        WHERE derniere_verification IS NULL 
                        OR derniere_verification < date('now', '-7 days')
                        OR niveau_danger LIKE '❌%'
                        LIMIT ?
                    '''
                    numeros = pd.read_sql(query, conn, params=[limite])
            else:
                if force:
                    query = '''
                        SELECT id, numero FROM numeros_sda
                    '''
                    numeros = pd.read_sql(query, conn)
                else:
                    # 👇 TOUS les numéros de la base
                    query = '''
                        SELECT id, numero FROM numeros_sda 
                        WHERE derniere_verification IS NULL 
                        OR derniere_verification < date('now', '-7 days')
                        OR niveau_danger LIKE '❌%'
                    '''
                    numeros = pd.read_sql(query, conn)
        
        conn.close()
        
        if len(numeros) == 0:
            return {"message": "✅ Tous les numéros sont à jour", "verifies": 0}
        
        # Barre de progression
        import streamlit as st
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        resultats = []
        total = len(numeros)
        
        for i, (_, row) in enumerate(numeros.iterrows()):
            status_text.text(f"🔍 Vérification {i+1}/{total} : {row['numero']}")
            resultat = self.verifier_et_mettre_a_jour(row['id'], row['numero'])
            resultats.append(resultat)
            progress_bar.progress((i + 1) / total)
            
            # Pause entre chaque numéro (rythme humain, sans surcharge)
            if i < total - 1:
                time.sleep(1.2)
        
        status_text.text("✅ Vérification terminée !")
        
        return {
            "message": f"✅ {len(numeros)} numéros vérifiés",
            "verifies": len(numeros),
            "details": resultats
        }