import phonenumbers
from phonenumbers import carrier, geocoder, timezone
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
from datetime import datetime
import random
import dns.resolver
import socket

class ReputationChecker:
    """
    Vérificateur de réputation pour numéros SDA
    Sources : Google Libphonenumber + Numeroinconnu.fr
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]
    


    def _resolve_with_dns(self, hostname):
        """Force la résolution DNS avec plusieurs serveurs"""
        dns_servers = ['8.8.8.8', '1.1.1.1', '208.67.222.222']
        
        for dns_server in dns_servers:
            try:
                resolver = dns.resolver.Resolver()
                resolver.nameservers = [dns_server]
                answers = resolver.resolve(hostname, 'A')
                ip = str(answers[0])
                print(f"✅ DNS {dns_server} → {ip}")
                return ip
            except Exception as e:
                print(f"⚠️ DNS {dns_server} échoué: {e}")
                continue
        
        # Fallback
        print("⚠️ Utilisation de la résolution système")
        return socket.gethostbyname(hostname)
    
    def _get_headers(self):
        """Génère des headers aléatoires"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3',
            'DNT': '1',
            'Connection': 'keep-alive'
        }
    
    def _get_status(self, score):
        """Convertit un score en statut visuel"""
        if score < 20:
            return "🟢 Très fiable"
        elif score < 40:
            return "🟢 Opérationnel"
        elif score < 60:
            return "🟡 À vérifier"
        elif score < 80:
            return "🟠 Risqué"
        else:
            return "🔴 Spammé"
    
    def _check_libphonenumber(self, number, country="FR"):
        """Vérification avec Google Libphonenumber"""
        result = {
            'valid': False,
            'type': 'inconnu',
            'carrier': 'inconnu',
            'location': 'inconnue',
            'timezone': 'inconnu'
        }
        
        try:
            num = phonenumbers.parse(number, country)
            result['valid'] = phonenumbers.is_valid_number(num)
            
            if result['valid']:
                # Type de ligne
                number_type = phonenumbers.number_type(num)
                type_map = {
                    0: "inconnu", 1: "📱 mobile", 2: "🏢 fixe",
                    3: "🏢 fixe", 4: "📞 personnel", 5: "📞 personnel",
                    6: "💻 voip", 7: "📞 personnel", 8: "📠 fax"
                }
                result['type'] = type_map.get(number_type, "inconnu")
                
                # Opérateur
                op = carrier.name_for_number(num, "fr")
                result['carrier'] = op if op else "inconnu"
                
                # Localisation
                loc = geocoder.description_for_number(num, "fr")
                result['location'] = loc if loc else "inconnue"
                
                # Fuseau horaire
                tz = timezone.time_zones_for_number(num)
                result['timezone'] = ', '.join(tz) if tz else "inconnu"
                
        except Exception as e:
            print(f"Erreur Libphonenumber: {e}")
        
        return result
    def _check_numeroinconnu(self, number, max_retries=2):
        """
        Recherche sur Numeroinconnu.fr avec gestion d'erreur DNS.
        Ne dépend pas de la configuration système.
        """
        result = {
            'comments': [],
            'danger_level': 'unknown',
            'danger_percentage': 0,
            'location': None,
            'visits': 0,
            'last_visit': None,
            'comments_count': 0
        }

        for attempt in range(1, max_retries + 1):
            try:
                print(f"🔍 Tentative {attempt}/{max_retries} pour {number}")

                # 👇 ON GARDE L'URL NORMALE AVEC LE NOM DE DOMAINE
                url = f"https://www.numeroinconnu.fr/numero/{number}"
                headers = self._get_headers()

                # Augmente un peu le timeout pour laisser le temps au DNS de répondre
                response = self.session.get(url, headers=headers, timeout=15)

                if response.status_code == 200:
                    # --- (Tout ton code de parsing HTML reste ici, à l'identique) ---
                    page_text = response.text
                    # Pourcentage de danger
                    pct_match = re.search(r'(\d+)\s*%', page_text)
                    if pct_match:
                        result['danger_percentage'] = int(pct_match.group(1))
                    # Niveau de danger
                    if "dangereux" in page_text.lower():
                        result['danger_level'] = 'high'
                    elif "gênant" in page_text.lower() or "genant" in page_text.lower():
                        result['danger_level'] = 'medium'
                    # ... (tout le reste de ton parsing)
                    # --- FIN DU CODE DE PARSING ---

                    print(f"   ✅ Succès! Danger: {result['danger_percentage']}%")
                    return result  # Succès, on sort

                else:
                    print(f"   ⚠️ Statut HTTP {response.status_code}")

            except requests.exceptions.ConnectionError as e:
                # 👇 C'EST LA QUE L'ERREUR DNS EST CAPTURÉE
                print(f"   ⚠️ Erreur de connexion (DNS ou réseau). Nouvelle tentative...")
                # On ne fait rien de spécial, on va juste réessayer après une pause
            except Exception as e:
                print(f"   ❌ Erreur inattendue: {e}")

            # Pause avant la prochaine tentative
            if attempt < max_retries:
                wait_time = attempt * 2
                print(f"   ⏳ Nouvelle tentative dans {wait_time}s...")
                time.sleep(wait_time)

        print(f"   ❌ Abandon après {max_retries} tentatives pour {number}")
        return result
                    
      
    
    def analyze_number(self, phone_number):
        """Analyse complète d'un numéro (Libphonenumber + Numeroinconnu)"""
        
        # Nettoyage
        clean_number = re.sub(r'[\s\-\(\)]', '', str(phone_number))
        
        # Structure du résultat
        result = {
            'number': phone_number,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'risk_score': 0,
            'type': 'inconnu',
            'carrier': 'inconnu',
            'location': 'inconnue',
            'comments': [],
            'numeroinconnu': {}
        }
        
        # ÉTAPE 1 : Google Libphonenumber
        basic = self._check_libphonenumber(clean_number)
        
        if not basic['valid']:
            result['risk_score'] = 100
            result['status'] = self._get_status(100)
            return result
        
        # Infos techniques
        result['type'] = basic['type']
        result['carrier'] = basic['carrier']
        result['location'] = basic['location']
        
        # Score de base
        if "voip" in basic['type']:
            result['risk_score'] += 30
        elif "mobile" in basic['type']:
            result['risk_score'] += 20
        elif "fixe" in basic['type']:
            result['risk_score'] += 10
        
        # ÉTAPE 2 : Numeroinconnu.fr
        time.sleep(1)  # Pause de courtoisie
        ni = self._check_numeroinconnu(clean_number)
        
        # Stocker toutes les données Numeroinconnu
        result['numeroinconnu'] = ni
        
        # Ajouter les commentaires
        result['comments'].extend(ni['comments'])
        
        # Ajuster le score selon le danger
        if ni['danger_percentage'] >= 70:
            result['risk_score'] += 60
        elif ni['danger_percentage'] >= 40:
            result['risk_score'] += 30
        elif ni['danger_percentage'] >= 10:
            result['risk_score'] += 10
        
        # Score final
        result['risk_score'] = min(result['risk_score'], 100)
        result['status'] = self._get_status(result['risk_score'])
        
        return result
    
    def batch_check(self, numbers, delay=2.0):
        """Vérifie une liste de numéros"""
        results = []
        total = len(numbers)
        
        print(f"\n{'='*50}")
        print(f"VÉRIFICATION DE {total} NUMÉROS")
        print(f"{'='*50}\n")
        
        for i, num in enumerate(numbers):
            print(f"[{i+1}/{total}] Analyse de {num}...")
            result = self.analyze_number(num)
            results.append(result)
            
            progress = (i + 1) / total * 100
            print(f"   → Progression: {progress:.1f}%")
            
            if i < total - 1:
                time.sleep(delay)
        
        return pd.DataFrame(results)