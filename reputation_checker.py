import phonenumbers
from phonenumbers import carrier, geocoder, timezone
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import re
import os
import sqlite3
import json
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ReputationChecker:
    def __init__(self, cache_db_path="reputation_cache.db", cache_ttl_hours=168):
        self.session = requests.Session()
        self.cache_db_path = cache_db_path
        self.cache_ttl_hours = cache_ttl_hours
        self.abstract_api_key = os.getenv("ABSTRACT_API_KEY", "").strip()
        self._setup_http_retry()
        self._init_cache_db()
        
        # Liste de user-agents de différents navigateurs
        self.user_agents = [
            # Chrome Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            # Chrome Mac
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            # Firefox
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
            # Safari
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            # Edge
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
            # Opera
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0',
            # Mobile (Android)
            'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            # Mobile (iPhone)
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1'
        ]

    def _setup_http_retry(self):
        """Configure une stratégie de retry HTTP robuste."""
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.8,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _normalize_number_for_numeroinconnu(self, number: str) -> str:
        """
        Normalise un numéro FR pour numeroinconnu.fr en format local 10 chiffres.
        Ex:
        - 33184782165 -> 0184782165
        - +33222910971 -> 0222910971
        - 0184782165 -> 0184782165
        """
        raw = re.sub(r"[^0-9+]", "", str(number).strip())
        digits = re.sub(r"[^0-9]", "", raw)

        # E.164 FR sans plus (33XXXXXXXXX) -> local 0XXXXXXXXX
        if digits.startswith("33") and len(digits) == 11:
            return "0" + digits[2:]

        # Déjà local FR correct
        if len(digits) == 10 and digits.startswith("0"):
            return digits

        # 9 chiffres nationaux sans 0
        if len(digits) == 9:
            return "0" + digits

        # Fallback: garder les chiffres tels quels
        return digits

    def _numeroinconnu_variants(self, local_10_digits: str):
        """
        Génère les variantes de format à tester sur numeroinconnu.fr.
        Ordre: local 0XXXXXXXXX, 33XXXXXXXXX, +33XXXXXXXXX
        """
        variants = []
        if local_10_digits and len(local_10_digits) == 10 and local_10_digits.startswith("0"):
            national_9 = local_10_digits[1:]
            variants = [
                local_10_digits,
                f"33{national_9}",
                f"+33{national_9}",
            ]
        else:
            variants = [local_10_digits]
        # Supprime les doublons en gardant l'ordre
        seen = set()
        uniq = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                uniq.append(v)
        return uniq

    def _init_cache_db(self):
        """Initialise le cache local SQLite pour les requêtes externes."""
        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reputation_cache (
                source TEXT NOT NULL,
                number TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (source, number)
            )
            """
        )
        conn.commit()
        conn.close()

    def _cache_get(self, source, number):
        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT response_json, created_at FROM reputation_cache WHERE source = ? AND number = ?",
            (source, number),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None

        payload, created_at = row
        created_dt = datetime.fromisoformat(created_at)
        age_hours = (datetime.now() - created_dt).total_seconds() / 3600
        if age_hours > self.cache_ttl_hours:
            return None
        try:
            return json.loads(payload)
        except Exception:
            return None

    def _cache_set(self, source, number, data):
        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reputation_cache (source, number, response_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, number) DO UPDATE SET
                response_json = excluded.response_json,
                created_at = excluded.created_at
            """,
            (source, number, json.dumps(data, ensure_ascii=False), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    
    def _get_headers(self):
        """Retourne des headers réalistes avec user-agent aléatoire"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
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
        """Recherche directe sur Numeroinconnu.fr"""
        result = {
            'comments': [],
            'danger_level': 'unknown',
            'danger_percentage': 0,
            'location': None,
            'visits': 0,
            'last_visit': None,
            'comments_count': 0,
            'error': None,
            'source_status': 'unknown'
        }
        
        # Normalisation
        clean_number = self._normalize_number_for_numeroinconnu(number)
        if len(clean_number) < 10:
            result['error'] = "Numéro invalide"
            result['source_status'] = 'invalid_number'
            return result

        cached = self._cache_get("numeroinconnu", clean_number)
        if cached is not None:
            cached['source_status'] = 'cache_hit'
            return cached
        
        print(f"🔍 Numéro original: {number} → Normalisé: {clean_number}")
        variants = self._numeroinconnu_variants(clean_number)
        
        # Pause humaine avant la requête
        time.sleep(random.uniform(2, 4))
        
        for attempt in range(max_retries):
            try:
                headers = self._get_headers()
                response = None
                used_variant = clean_number
                for candidate in variants:
                    url = f"https://www.numeroinconnu.fr/numero/{candidate}"
                    print(f"🔍 Tentative {attempt+1}/{max_retries} pour {candidate}")
                    resp = self.session.get(url, headers=headers, timeout=20)
                    if resp.status_code == 200:
                        response = resp
                        used_variant = candidate
                        break
                    # On continue sur la variante suivante si non trouvé
                    if resp.status_code == 404:
                        continue
                    # Pour les autres statuts, garder la réponse et sortir
                    response = resp
                    used_variant = candidate
                    break

                if response is None:
                    result['error'] = "Numéro non trouvé"
                    result['source_status'] = 'not_found'
                    self._cache_set("numeroinconnu", clean_number, result)
                    return result
                
                if response.status_code == 200:
                    page_text = response.text
                    print(f"✅ Succès pour {used_variant}")

                    soup = BeautifulSoup(response.text, 'lxml')

                    # Parsing plus robuste du pourcentage (cherche d'abord autour de mots-clés)
                    pct_match = re.search(
                        r'(danger|fiabilit[ée]|risque)[^0-9]{0,20}(\d{1,3})\s*%',
                        page_text,
                        re.I
                    )
                    if pct_match:
                        result['danger_percentage'] = min(100, max(0, int(pct_match.group(2))))
                    else:
                        fallback_pct = re.search(r'(\d{1,3})\s*%', page_text)
                        if fallback_pct:
                            result['danger_percentage'] = min(100, max(0, int(fallback_pct.group(1))))

                    # Niveau de danger textuel
                    if re.search(r'dangereux|arnaque|spam', page_text, re.I):
                        result['danger_level'] = 'high'
                    elif re.search(r'g[êe]nant|soup[çc]on|ind[ée]sirable', page_text, re.I):
                        result['danger_level'] = 'medium'
                    elif result['danger_percentage'] > 0:
                        result['danger_level'] = 'low'

                    # Localisation/statistiques
                    loc_match = re.search(r'Ville\s*:\s*([^\n<]+)', page_text, re.I)
                    if loc_match:
                        result['location'] = loc_match.group(1).strip()

                    visits_match = re.search(r'Nombre\s*de\s*visites?\s*:?\s*(\d+)', page_text, re.I)
                    if visits_match:
                        result['visits'] = int(visits_match.group(1))

                    last_match = re.search(r'Derni[èe]re\s*visite\s*:?\s*([0-9/]+)', page_text, re.I)
                    if last_match:
                        result['last_visit'] = last_match.group(1).strip()

                    comments_match = re.search(r'Nombre\s*de\s*commentaires?\s*:?\s*(\d+)', page_text, re.I)
                    if comments_match:
                        result['comments_count'] = int(comments_match.group(1))

                    # Commentaires
                    comment_sections = soup.find_all(
                        ['div', 'p'],
                        class_=re.compile(r'comment|avis|message|review', re.I)
                    )
                    for section in comment_sections[:5]:
                        text = section.get_text().strip()
                        if text and len(text) > 20:
                            clean = re.sub(r'\s+', ' ', text)
                            result['comments'].append(f"💬 {clean[:150]}...")

                    result['source_status'] = 'ok'
                    self._cache_set("numeroinconnu", clean_number, result)
                    print(f"   → Danger: {result['danger_percentage']}%")
                    return result
                    
                elif response.status_code == 404:
                    print(f"⚠️ Numéro {used_variant} non trouvé")
                    result['error'] = "Numéro non trouvé"
                    result['source_status'] = 'not_found'
                    self._cache_set("numeroinconnu", clean_number, result)
                    return result
                elif response.status_code in [403, 429]:
                    result['error'] = f"Bloqué par la source ({response.status_code})"
                    result['source_status'] = 'blocked'
                else:
                    print(f"⚠️ Statut {response.status_code}")
                    result['error'] = f"HTTP {response.status_code}"
                    result['source_status'] = 'http_error'
                    
            except Exception as e:
                print(f"❌ Erreur: {e}")
                result['error'] = str(e)
                result['source_status'] = 'network_error'
            
            if attempt < max_retries - 1:
                wait_time = random.uniform(3, 6)
                print(f"   ⏳ Pause de {wait_time:.1f}s...")
                time.sleep(wait_time)
        
        print(f"❌ ÉCHEC pour {clean_number}")
        result['error'] = "Vérification échouée"
        result['source_status'] = 'failed'
        
        return result

    def _check_abstractapi(self, number):
        """Fallback optionnel via AbstractAPI (si clé API fournie)."""
        result = {
            "valid": None,
            "line_type": None,
            "carrier": None,
            "location": None,
            "error": None,
            "source_status": "disabled",
        }
        if not self.abstract_api_key:
            return result

        clean_number = re.sub(r'[^0-9+]', '', str(number))
        cached = self._cache_get("abstractapi", clean_number)
        if cached is not None:
            cached["source_status"] = "cache_hit"
            return cached

        try:
            url = "https://phonevalidation.abstractapi.com/v1/"
            response = self.session.get(
                url,
                params={"api_key": self.abstract_api_key, "phone": clean_number},
                timeout=15,
            )
            if response.status_code != 200:
                result["error"] = f"HTTP {response.status_code}"
                result["source_status"] = "http_error"
                return result

            data = response.json()
            result["valid"] = data.get("valid")
            result["line_type"] = (data.get("phone_carrier") or {}).get("line_type")
            result["carrier"] = (data.get("phone_carrier") or {}).get("name")
            city = (data.get("phone_location") or {}).get("city")
            country = (data.get("phone_location") or {}).get("country")
            result["location"] = ", ".join([x for x in [city, country] if x]) or None
            result["source_status"] = "ok"
            self._cache_set("abstractapi", clean_number, result)
            return result
        except Exception as e:
            result["error"] = str(e)
            result["source_status"] = "network_error"
            return result
    
    def analyze_number(self, phone_number):
        """Analyse complète d'un numéro"""
        
        # Nettoyage
        clean_number = re.sub(r'[\s\-\(\)]', '', str(phone_number))
        
        # Structure du résultat
        result = {
            'number': phone_number,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'risk_score': 0,
            'confidence': 'low',
            'type': 'inconnu',
            'carrier': 'inconnu',
            'location': 'inconnue',
            'comments': [],
            'numeroinconnu': {},
            'abstractapi': {},
            'reasons': []
        }
        
        # ÉTAPE 1 : Google Libphonenumber
        basic = self._check_libphonenumber(clean_number)
        
        if not basic['valid']:
            result['risk_score'] = 100
            result['status'] = self._get_status(100)
            result['reasons'].append("Numéro invalide (libphonenumber)")
            return result
        
        # Infos techniques
        result['type'] = basic['type']
        result['carrier'] = basic['carrier']
        result['location'] = basic['location']
        
        # Score de base
        if "voip" in basic['type']:
            result['risk_score'] += 30
            result['reasons'].append("Type VOIP (+30)")
        elif "mobile" in basic['type']:
            result['risk_score'] += 20
            result['reasons'].append("Type mobile (+20)")
        elif "fixe" in basic['type']:
            result['risk_score'] += 10
            result['reasons'].append("Type fixe (+10)")
        
        # ÉTAPE 2 : Numeroinconnu.fr avec délai aléatoire
        time.sleep(random.uniform(1, 2))  # Délai variable entre 1 et 2 secondes
        ni = self._check_numeroinconnu(clean_number)
        
        # Stocker toutes les données Numeroinconnu
        result['numeroinconnu'] = ni
        
        # Ajouter les commentaires
        result['comments'].extend(ni['comments'])
        
        # Ajuster le score selon le danger
        if ni.get('source_status') in ['ok', 'cache_hit']:
            result['confidence'] = 'high'
            if ni['danger_percentage'] >= 70:
                result['risk_score'] += 60
                result['reasons'].append("Numeroinconnu danger >= 70% (+60)")
            elif ni['danger_percentage'] >= 40:
                result['risk_score'] += 30
                result['reasons'].append("Numeroinconnu danger >= 40% (+30)")
            elif ni['danger_percentage'] >= 10:
                result['risk_score'] += 10
                result['reasons'].append("Numeroinconnu danger >= 10% (+10)")
            else:
                result['reasons'].append("Numeroinconnu sans signal fort")
        else:
            result['reasons'].append(f"Numeroinconnu indisponible ({ni.get('source_status', 'unknown')})")
            # On évite le faux sentiment de sécurité quand la source est indisponible.
            result['risk_score'] += 10
            result['confidence'] = 'medium'

        # ÉTAPE 3 : Fallback AbstractAPI (optionnel)
        abstract = self._check_abstractapi(clean_number)
        result['abstractapi'] = abstract
        if abstract.get("source_status") in ["ok", "cache_hit"]:
            if abstract.get("line_type") and "voip" in str(abstract.get("line_type")).lower():
                result['risk_score'] += 10
                result['reasons'].append("AbstractAPI détecte ligne VOIP (+10)")
            if result['carrier'] == "inconnu" and abstract.get("carrier"):
                result['carrier'] = abstract.get("carrier")
            if result['location'] == "inconnue" and abstract.get("location"):
                result['location'] = abstract.get("location")
            if result['confidence'] == 'low':
                result['confidence'] = 'medium'
        
        # Score final
        result['risk_score'] = min(result['risk_score'], 100)
        result['status'] = self._get_status(result['risk_score'])
        
        return result
    
    def batch_check(self, numbers, delay=2.0):
        """Vérifie une liste de numéros avec délai aléatoire"""
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
            
            # Délai aléatoire entre les requêtes
            if i < total - 1:
                wait = random.uniform(delay, delay + 2)
                print(f"   → Pause de {wait:.1f}s")
                time.sleep(wait)
        
        return pd.DataFrame(results)
    
    def save_results(self, df, filename=None):
        """Sauvegarde les résultats en CSV"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"verification_{timestamp}.csv"
        
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"✅ Résultats sauvegardés : {filename}")
        return filename