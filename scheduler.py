import schedule
import time
import threading
from datetime import datetime
import streamlit as st

class VerificationScheduler:
    def __init__(self, db_path='sda_database.db'):
        self.db_path = db_path
        self.running = False
        self.thread = None
        self.heure_programmee = None
    
    def job_verification(self):
        """Tâche à exécuter à l'heure programmée"""
        print(f"⏰ [{datetime.now()}] Lancement de la vérification automatique")
        
        # Récupérer l'alerter
        from email_alerter import EmailAlerter
        from sda_operations import SDAManager
        
        # 1. Lancer une vérification sur tous les numéros non vérifiés
        sda_manager = SDAManager(self.db_path)
        resultat = sda_manager.verifier_lot(limite=100)
        print(f"   ✅ {resultat['verifies']} numéros vérifiés")
        
        # 2. Vérifier les nouveaux spams
        alerter = EmailAlerter(self.db_path)
        nouveaux_spams = alerter.verifier_nouveaux_spams()
        
        # 3. Envoyer une alerte s'il y a des spams
        if not nouveaux_spams.empty:
            alerter.envoyer_alerte_spams(nouveaux_spams)
            print(f"   🚨 Alerte envoyée pour {len(nouveaux_spams)} spams")
        else:
            print("   ✅ Aucun nouveau spam détecté")
    
    def programmer(self, heure):
        """Programme la vérification quotidienne"""
        self.heure_programmee = heure
        
        # Nettoyer les anciennes programmations
        schedule.clear()
        
        # Programmer la nouvelle tâche
        schedule.every().day.at(heure).do(self.job_verification)
        print(f"⏰ Vérification programmée tous les jours à {heure}")
        
        if not self.running:
            self.demarrer()
    
    def demarrer(self):
        """Démarre le scheduler dans un thread séparé"""
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()
        print("✅ Scheduler démarré")
    
    def _run(self):
        """Boucle principale du scheduler"""
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Vérifier chaque minute
    
    def arreter(self):
        """Arrête le scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("⏹️ Scheduler arrêté")