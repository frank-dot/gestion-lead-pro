import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sqlite3
from datetime import datetime
import pandas as pd

class EmailAlerter:
    def __init__(self, db_path='sda_database.db'):
        self.db_path = db_path
        self.config = self.charger_config()
        self._creer_table_historique()
    
    def charger_config(self):
        """Charge la configuration email depuis la base"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Vérifier si la colonne existe
        cursor.execute("PRAGMA table_info(config_alertes)")
        colonnes = [col[1] for col in cursor.fetchall()]
        
        if 'date_config' not in colonnes:
            # Ajouter la colonne manquante
            cursor.execute("ALTER TABLE config_alertes ADD COLUMN date_config TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        
        # Récupérer la dernière config active
        cursor.execute('''
            SELECT smtp_server, smtp_port, email_expediteur, 
                password, destinataires 
            FROM config_alertes 
            WHERE actif = 1 
            ORDER BY date_config DESC LIMIT 1
        ''')
        
        result = cursor.fetchone()
        conn.commit()
        conn.close()
        
        if result:
            return {
                'smtp_server': result[0],
                'smtp_port': result[1],
                'email': result[2],
                'password': result[3],
                'destinataires': result[4].split(',') if result[4] else []
            }
        return None
    
    def sauvegarder_config(self, smtp_server, smtp_port, email, password, destinataires):
        """Sauvegarde la configuration email"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Désactiver les anciennes configs
        cursor.execute("UPDATE config_alertes SET actif = 0")
        
        # Ajouter la nouvelle config
        destinataires_str = ','.join(destinataires)
        cursor.execute('''
            INSERT INTO config_alertes 
            (smtp_server, smtp_port, email_expediteur, password, destinataires, actif)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (smtp_server, smtp_port, email, password, destinataires_str))
        
        conn.commit()
        conn.close()
        self.config = self.charger_config()
        return True
    
    def verifier_nouveaux_spams(self):
        """Vérifie les numéros devenus spams depuis la dernière alerte"""
        # Créer les tables si elles n'existent pas
        self._creer_table_historique()
        
        conn = sqlite3.connect(self.db_path)
        
        # Récupérer la dernière alerte envoyée
        cursor = conn.cursor()
        cursor.execute('''
            SELECT MAX(date_alerte) FROM historique_alertes
        ''')
        derniere_alerte = cursor.fetchone()[0]
            
        if not derniere_alerte:
            derniere_alerte = '1970-01-01'
        
        # Chercher les nouveaux spams
        query = '''
            SELECT n.numero, p.nom as prestataire, 
                   h.danger_percentage, h.niveau_danger,
                   h.date_verification
            FROM historique_verifications h
            JOIN numeros_sda n ON h.numero_id = n.id
            JOIN prestataires p ON n.prestataire_id = p.id
            WHERE h.danger_percentage >= 50
            AND h.date_verification > ?
            ORDER BY h.date_verification DESC
        '''
        nouveaux = pd.read_sql(query, conn, params=[derniere_alerte])
        conn.close()
        
        return nouveaux
    
    def envoyer_alerte_spams(self, nouveaux_spams):
        """Envoie un email avec la liste des nouveaux spams"""
        if not self.config:
            print("❌ Configuration email manquante")
            return False
        
        if nouveaux_spams.empty:
            print("✅ Aucun nouveau spam à signaler")
            return True
        
        sujet = f"🚨 ALERTE SPAM - {len(nouveaux_spams)} nouveau(x) numéro(s) détecté(s)"
        
        # Construction du corps HTML
        corps = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                h2 {{ color: #e74c3c; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                th {{ background-color: #e74c3c; color: white; padding: 10px; text-align: left; }}
                td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
                .danger {{ color: #e74c3c; font-weight: bold; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #777; }}
            </style>
        </head>
        <body>
            <h2>🚨 Alerte Spam Automatique</h2>
            <p><strong>Date :</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
            <p><strong>{len(nouveaux_spams)} nouveau(x) numéro(s) spammé(s) détecté(s) :</strong></p>
            
            <table>
                <tr>
                    <th>Numéro</th>
                    <th>Prestataire</th>
                    <th>Danger</th>
                    <th>Date vérification</th>
                </tr>
        """
        
        for _, spam in nouveaux_spams.iterrows():
            corps += f"""
                <tr>
                    <td>{spam['numero']}</td>
                    <td>{spam['prestataire']}</td>
                    <td class="danger">{spam['danger_percentage']}% - {spam['niveau_danger']}</td>
                    <td>{spam['date_verification']}</td>
                </tr>
            """
        
        corps += """
            </table>
            <p>Connectez-vous à l'application pour plus de détails.</p>
            <div class="footer">
                Cet email a été envoyé automatiquement par votre application de gestion SDA.
            </div>
        </body>
        </html>
        """
        
        # Envoyer à tous les destinataires
        succes = True
        for destinataire in self.config['destinataires']:
            if not self._envoyer_email(destinataire, sujet, corps):
                succes = False
        
        if succes:
            # Enregistrer l'envoi
            self._enregistrer_alerte(len(nouveaux_spams))
            print(f"✅ Alerte envoyée pour {len(nouveaux_spams)} spams")
        
        return succes
    
    def _envoyer_email(self, destinataire, sujet, corps_html):
        """Envoie un email via SMTP"""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = sujet
            msg['From'] = self.config['email']
            msg['To'] = destinataire
            
            part_html = MIMEText(corps_html, 'html')
            msg.attach(part_html)
            
            server = smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port'])
            server.starttls()
            server.login(self.config['email'], self.config['password'])
            server.send_message(msg)
            server.quit()
            
            print(f"✅ Email envoyé à {destinataire}")
            return True
            
        except Exception as e:
            print(f"❌ Erreur envoi email à {destinataire}: {e}")
            return False
    
    def _enregistrer_alerte(self, nombre_spams):
        """Enregistre l'envoi d'alerte dans l'historique"""
        # Créer la table si elle n'existe pas
        self._creer_table_historique()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO historique_alertes (nombre_spams, destinataires)
            VALUES (?, ?)
        ''', (nombre_spams, ','.join(self.config['destinataires'])))
        
        conn.commit()
        conn.close()
    
    def _creer_table_historique(self):
        """Crée la table d'historique des alertes si elle n'existe pas"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS historique_alertes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_alerte TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                nombre_spams INTEGER,
                destinataires TEXT
            )
        ''')
        
        conn.commit()
        conn.close()