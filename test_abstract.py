import requests
import json
import urllib.parse

# 🔑 TA VRAIE CLÉ
API_KEY = "40e486131a1244d39edff3f4b4ab8a8a"
NUMERO_A_TESTER = "+33222910970"

# Encoder le numéro pour l'URL
numero_encode = urllib.parse.quote(NUMERO_A_TESTER)

# URL correcte avec numéro encodé
url = f"https://phonevalidation.abstractapi.com/v1/?api_key={API_KEY}&phone={numero_encode}"

print(f"🔍 URL testée: {url}")

try:
    print(f"🔍 Test Abstract API pour {NUMERO_A_TESTER}...")
    response = requests.get(url)
    data = response.json()
    
    print("\n📊 RÉSULTAT BRUT:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    if data.get('phone_validation', {}).get('is_valid'):
        print("\n✅ NUMÉRO VALIDE")
        print(f"   • Type: {data.get('phone_carrier', {}).get('line_type', 'inconnu')}")
        print(f"   • Opérateur: {data.get('phone_carrier', {}).get('name', 'inconnu')}")
        print(f"   • Localisation: {data.get('phone_location', {}).get('city', 'inconnue')}")
    else:
        print("\n❌ NUMÉRO INVALIDE")
        if 'error' in data:
            print(f"   • Erreur: {data['error'].get('message', 'Erreur inconnue')}")
            
except Exception as e:
    print(f"❌ Erreur de connexion: {e}")

print("\n--- FIN DU TEST ---")