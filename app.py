import streamlit as st
import pandas as pd
import re
from datetime import datetime
from collections import Counter
import io
import json
import hashlib
import random

# ============================================================================
# CONFIGURATION INITIALE
# ============================================================================
st.set_page_config(
    page_title="GestLead Pro",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================================
# CONSTANTES
# ============================================================================
FICHIER_UTILISATEURS = "utilisateurs.json"

# ============================================================================
# FONCTIONS D'AUTHENTIFICATION (CORRIGÉES)
# ============================================================================
def hash_password(password):
    """Hash un mot de passe avec sel - encodage UTF-8"""
    salt = "gestlead_pro_salt_2024"
    # Encodage explicite en UTF-8
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()

def verifier_mot_de_passe(mot_de_passe, hash_stocke):
    """Vérifie si le mot de passe correspond au hash"""
    return hash_password(mot_de_passe) == hash_stocke

def charger_utilisateurs():
    """Charge la liste des utilisateurs depuis le fichier avec encodage UTF-8"""
    try:
        with open(FICHIER_UTILISATEURS, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Créer un utilisateur par défaut sans emojis pour éviter les problèmes d'encodage
        utilisateurs_defaut = {
            "admin": {
                "nom": "Administrateur",
                "mot_de_passe": hash_password("admin123"),
                "role": "admin",
                "avatar": "👨‍💼",  # On garde l'emoji mais avec UTF-8 ça fonctionne
                "couleur": "#FF6B6B",
                "date_creation": datetime.now().isoformat(),
                "derniere_connexion": None
            }
        }
        sauvegarder_utilisateurs(utilisateurs_defaut)
        return utilisateurs_defaut
    except Exception as e:
        # En cas d'erreur, recréer le fichier
        st.error(f"Erreur de chargement: {e}")
        utilisateurs_defaut = {
            "admin": {
                "nom": "Administrateur",
                "mot_de_passe": hash_password("admin123"),
                "role": "admin",
                "avatar": "👨‍💼",
                "couleur": "#FF6B6B",
                "date_creation": datetime.now().isoformat(),
                "derniere_connexion": None
            }
        }
        sauvegarder_utilisateurs(utilisateurs_defaut)
        return utilisateurs_defaut

def sauvegarder_utilisateurs(utilisateurs):
    """Sauvegarde la liste des utilisateurs avec encodage UTF-8"""
    try:
        with open(FICHIER_UTILISATEURS, 'w', encoding='utf-8') as f:
            json.dump(utilisateurs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        st.error(f"Erreur de sauvegarde: {e}")

def creer_utilisateur(identifiant, nom, mot_de_passe, role="user"):
    """Crée un nouvel utilisateur"""
    utilisateurs = charger_utilisateurs()
    
    if identifiant in utilisateurs:
        return False, "Cet identifiant existe déjà"
    
    # Liste d'avatars (avec emojis)
    avatars = ["👨‍💼", "👩‍💼", "👨‍🔧", "👩‍🔧", "👨‍🎨", "👩‍🎨", "👨‍🚀", "👩‍🚀", "🦸", "🦸‍♀️"]
    couleurs = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEEAD", "#D4A5A5", "#9B59B6", "#3498DB", "#E67E22", "#2ECC71"]
    
    utilisateurs[identifiant] = {
        "nom": nom,
        "mot_de_passe": hash_password(mot_de_passe),
        "role": role,
        "avatar": random.choice(avatars),
        "couleur": random.choice(couleurs),
        "date_creation": datetime.now().isoformat(),
        "derniere_connexion": None
    }
    
    sauvegarder_utilisateurs(utilisateurs)
    return True, "Utilisateur créé avec succès"

def authentifier(identifiant, mot_de_passe):
    """Authentifie un utilisateur"""
    utilisateurs = charger_utilisateurs()
    
    if identifiant not in utilisateurs:
        return False, "Identifiant incorrect"
    
    if not verifier_mot_de_passe(mot_de_passe, utilisateurs[identifiant]["mot_de_passe"]):
        return False, "Mot de passe incorrect"
    
    # Mettre à jour la dernière connexion
    utilisateurs[identifiant]["derniere_connexion"] = datetime.now().isoformat()
    sauvegarder_utilisateurs(utilisateurs)
    
    return True, utilisateurs[identifiant]

# ============================================================================
# INITIALISATION DE LA SESSION
# ============================================================================
def init_session_state():
    """Initialise toutes les variables de session au démarrage"""
    defaults = {
        'authentifie': False,
        'page': 'login',
        'utilisateur': None,
        'identifiant': '',
        'role': None,
        'avatar': '👤',
        'couleur': '#667eea',
        'df_original': None,
        'df_travail': None,
        'nom_fichier': '',
        'historique_actions': [],
        'position_historique': -1,
        'historique_exports': [],
        'tableau_de_bord': {
            'total_exports': 0,
            'total_lignes_exportees': 0,
            'formats_utilises': {},
            'dernier_export': None
        }
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# FONCTIONS DE GESTION D'ÉTAT
# ============================================================================
def sauvegarder_etat(df):
    """Sauvegarde l'état actuel dans l'historique des actions"""
    st.session_state.historique_actions = st.session_state.historique_actions[:st.session_state.position_historique + 1]
    st.session_state.historique_actions.append({
        'timestamp': datetime.now(),
        'dataframe': df.copy(),
        'action': st.session_state.page
    })
    st.session_state.position_historique += 1

def annuler():
    """Annule la dernière modification"""
    if st.session_state.position_historique > 0:
        st.session_state.position_historique -= 1
        return st.session_state.historique_actions[st.session_state.position_historique]['dataframe'].copy()
    return st.session_state.df_original.copy()

def refaire():
    """Refait la dernière modification annulée"""
    if st.session_state.position_historique < len(st.session_state.historique_actions) - 1:
        st.session_state.position_historique += 1
        return st.session_state.historique_actions[st.session_state.position_historique]['dataframe'].copy()
    return st.session_state.df_travail.copy()

def enregistrer_export(nom_fichier, format_export, lignes, colonnes):
    """Enregistre un export dans l'historique"""
    export = {
        'id': len(st.session_state.historique_exports) + 1,
        'timestamp': datetime.now(),
        'nom_fichier': nom_fichier,
        'format': format_export,
        'lignes': lignes,
        'colonnes': colonnes,
        'fichier_source': st.session_state.nom_fichier,
        'utilisateur': st.session_state.identifiant,
        'avatar': st.session_state.avatar,
        'taille_ko': 0
    }
    
    st.session_state.historique_exports.append(export)
    
    # Mettre à jour le tableau de bord
    st.session_state.tableau_de_bord['total_exports'] += 1
    st.session_state.tableau_de_bord['total_lignes_exportees'] += lignes
    st.session_state.tableau_de_bord['formats_utilises'][format_export] = st.session_state.tableau_de_bord['formats_utilises'].get(format_export, 0) + 1
    st.session_state.tableau_de_bord['dernier_export'] = export

def se_connecter(identifiant, infos_utilisateur):
    """Gère la connexion"""
    st.session_state.authentifie = True
    st.session_state.utilisateur = infos_utilisateur["nom"]
    st.session_state.identifiant = identifiant
    st.session_state.role = infos_utilisateur["role"]
    st.session_state.avatar = infos_utilisateur.get("avatar", "👤")
    st.session_state.couleur = infos_utilisateur.get("couleur", "#667eea")
    st.session_state.page = "accueil"

def se_deconnecter():
    """Gère la déconnexion"""
    st.session_state.authentifie = False
    st.session_state.page = "login"
    st.session_state.utilisateur = None
    st.session_state.identifiant = None
    st.session_state.role = None
    st.session_state.avatar = '👤'
    st.session_state.couleur = '#667eea'
    st.session_state.df_original = None
    st.session_state.df_travail = None
    st.session_state.nom_fichier = ''
    st.session_state.historique_actions = []
    st.session_state.position_historique = -1

def sauvegarder_session():
    """Sauvegarde la session dans un fichier JSON avec encodage UTF-8"""
    session_data = {
        'utilisateur': st.session_state.identifiant,
        'nom': st.session_state.utilisateur,
        'avatar': st.session_state.avatar,
        'date_sauvegarde': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'fichier_actuel': st.session_state.nom_fichier,
        'lignes': len(st.session_state.df_travail) if st.session_state.df_travail is not None else 0,
        'colonnes': len(st.session_state.df_travail.columns) if st.session_state.df_travail is not None else 0,
        'historique_exports': [
            {
                'date': e['timestamp'].strftime('%d/%m/%Y %H:%M'),
                'fichier': e['nom_fichier'],
                'format': e['format'],
                'lignes': e['lignes']
            } for e in st.session_state.historique_exports[-10:]
        ],
        'tableau_de_bord': st.session_state.tableau_de_bord
    }
    
    return json.dumps(session_data, indent=2, ensure_ascii=False)

def charger_session(session_json):
    """Charge une session depuis un JSON"""
    try:
        data = json.loads(session_json)
        if data.get('utilisateur') == st.session_state.identifiant:
            st.success(f"✅ Session chargée: {data.get('date_sauvegarde', '')}")
            return True
        else:
            st.error("❌ Cette session n'appartient pas à l'utilisateur connecté")
            return False
    except:
        return False

def aller_a(page):
    """Navigation entre les pages"""
    st.session_state.page = page
    st.rerun()

# ============================================================================
# FONCTIONS DE TRAITEMENT DES DONNÉES
# ============================================================================
def verifier_colonnes_en_double(df):
    """Vérifie si des colonnes en double existent"""
    if len(df.columns) != len(set(df.columns)):
        compteur = Counter(df.columns)
        doublons = [col for col, count in compteur.items() if count > 1]
        return True, doublons
    return False, []

def renommer_colonnes_doublons(df):
    """Renomme les colonnes en double"""
    nouveaux_noms = []
    compteur_vu = {}
    for col in df.columns:
        if col not in compteur_vu:
            compteur_vu[col] = 1
            nouveaux_noms.append(col)
        else:
            compteur_vu[col] += 1
            nouveaux_noms.append(f"{col}_{compteur_vu[col]}")
    df.columns = nouveaux_noms
    return df

def formater_telephone(numero, format_choisi):
    """Nettoie et formate un numéro de téléphone"""
    if pd.isna(numero):
        return numero
    
    clean = re.sub(r'[^0-9]', '', str(numero))
    
    if not clean:
        return numero
    
    if clean.startswith('33') and len(clean) > 2:
        clean = clean[2:]
    
    if len(clean) > 9:
        clean = clean[-9:]
    
    if format_choisi == "33":
        return "33" + clean
    elif format_choisi == "0":
        return "0" + clean
    else:
        return clean

def extraire_code_postal(texte):
    """Extrait un code postal français (5 chiffres) d'un texte"""
    if pd.isna(texte):
        return None
    match = re.search(r'\b(\d{5})\b', str(texte))
    if match:
        return match.group(1)
    return None

def detecter_encodage_et_separateur(fichier):
    """Détecte automatiquement l'encodage et le séparateur d'un fichier CSV"""
    raw_data = fichier.getvalue()
    
    encodages = ['latin1', 'cp1252', 'utf-8', 'iso-8859-1']
    
    for enc in encodages:
        try:
            content = raw_data.decode(enc).split('\n')[0]
            
            virgules = content.count(',')
            points_virgules = content.count(';')
            tabulations = content.count('\t')
            
            if points_virgules > virgules and points_virgules > tabulations:
                sep = ';'
            elif tabulations > virgules and tabulations > points_virgules:
                sep = '\t'
            else:
                sep = ','
            
            fichier.seek(0)
            pd.read_csv(fichier, sep=sep, encoding=enc, nrows=5)
            
            fichier.seek(0)
            return enc, sep
            
        except:
            continue
    
    return None, None

# ============================================================================
# CSS PERSONNALISÉ
# ============================================================================
def appliquer_style():
    """Applique le CSS personnalisé à l'application"""
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        * {
            font-family: 'Inter', sans-serif;
        }
        
        /* Style des boutons */
        .stButton > button {
            border-radius: 12px;
            font-weight: 600;
            transition: all 0.3s ease;
            border: none;
            padding: 0.75rem 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
            color: white;
        }
        
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.15);
        }
        
        .stButton > button:active {
            transform: translateY(0);
        }
        
        /* Style des cartes */
        .css-card {
            background: white;
            padding: 1.5rem;
            border-radius: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            border: 1px solid rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
        }
        
        .css-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 40px rgba(0,0,0,0.15);
        }
        
        /* Style des métriques */
        .metric-card {
            background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
            color: white;
            padding: 1.5rem;
            border-radius: 15px;
            text-align: center;
            box-shadow: 0 10px 20px rgba(255,107,107,0.3);
        }
        
        /* Style des avatars */
        .avatar-circle {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2rem;
            box-shadow: 0 4px 10px rgba(0,0,0,0.2);
        }
        
        /* Animation de chargement */
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.05); }
            100% { transform: scale(1); }
        }
        
        .pulse-animation {
            animation: pulse 2s infinite;
        }
        
        /* Style des notifications */
        .success-notification {
            background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
            color: white;
            padding: 1rem;
            border-radius: 10px;
            text-align: center;
            font-weight: 600;
        }
        
        /* Style des onglets */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            background-color: #f8f9fa;
            padding: 0.5rem;
            border-radius: 50px;
        }
        
        .stTabs [data-baseweb="tab"] {
            border-radius: 50px;
            padding: 0.5rem 1.5rem;
            font-weight: 600;
        }
        
        .stTabs [aria-selected="true"] {
            background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
            color: white !important;
        }
        
        /* Style des barres de progression */
        .stProgress > div > div {
            background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
            border-radius: 10px;
        }
        
        /* Style des inputs */
        .stTextInput > div > div > input {
            border-radius: 12px;
            border: 2px solid #e0e0e0;
            padding: 0.75rem;
            font-size: 1rem;
            transition: all 0.3s ease;
        }
        
        .stTextInput > div > div > input:focus {
            border-color: #FF6B6B;
            box-shadow: 0 0 0 3px rgba(255,107,107,0.1);
        }
        
        /* Style des selectbox */
        .stSelectbox > div > div {
            border-radius: 12px;
            border: 2px solid #e0e0e0;
        }
        
        /* Style des expanders */
        .streamlit-expanderHeader {
            background-color: #f8f9fa;
            border-radius: 12px;
            font-weight: 600;
        }
        
        /* Pied de page */
        .footer {
            text-align: center;
            padding: 2rem;
            color: #999;
            font-size: 0.9rem;
        }
        </style>
    """, unsafe_allow_html=True)

# ============================================================================
# COMPOSANTS D'INTERFACE RÉUTILISABLES
# ============================================================================
def afficher_barre_laterale():
    """Affiche la barre latérale avec les infos utilisateur"""
    with st.sidebar:
        # En-tête avec avatar personnalisé
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"""
                <div class="avatar-circle" style="background: {st.session_state.couleur};">
                    {st.session_state.avatar}
                </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown(f"### {st.session_state.utilisateur}")
            st.markdown(f"*@{st.session_state.identifiant}*")
            if st.session_state.role == "admin":
                st.markdown("🛡️ **Administrateur**")
        
        st.markdown("---")
        
        # Date et heure avec style
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"📅 {datetime.now().strftime('%d/%m/%Y')}")
        with col2:
            st.markdown(f"⏰ {datetime.now().strftime('%H:%M')}")
        
        if st.session_state.df_original is not None:
            st.markdown("---")
            st.markdown("### 📁 Fichier actuel")
            
            # Carte du fichier
            st.markdown(f"""
                <div style="background: #f8f9fa; padding: 1rem; border-radius: 12px;">
                    <div style="font-weight: 600;">{st.session_state.nom_fichier}</div>
                    <div style="color: #666;">{len(st.session_state.df_original)} lignes</div>
                </div>
            """, unsafe_allow_html=True)
            
            if len(st.session_state.historique_actions) > 1:
                st.markdown("---")
                st.markdown("### 🔄 Historique")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("↩️ Annuler", use_container_width=True):
                        df = annuler()
                        if df is not None:
                            st.session_state.df_travail = df
                            st.rerun()
                with col2:
                    if st.button("↪️ Refaire", use_container_width=True):
                        df = refaire()
                        if df is not None:
                            st.session_state.df_travail = df
                            st.rerun()
        
        # Section Sauvegarde
        st.markdown("---")
        st.markdown("### 💾 Sauvegarde")
        
        if st.button("📥 Sauvegarder", use_container_width=True):
            session_json = sauvegarder_session()
            st.download_button(
                label="📥 Télécharger",
                data=session_json,
                file_name=f"session_{st.session_state.identifiant}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )
        
        uploaded_session = st.file_uploader("Charger une session", type=['json'], key="session_upload")
        if uploaded_session is not None:
            session_data = uploaded_session.read().decode('utf-8')
            if charger_session(session_data):
                st.success("✅ Session chargée!")
        
        st.markdown("---")
        if st.button("🚪 Déconnexion", use_container_width=True):
            se_deconnecter()
            st.rerun()

def afficher_carte_fonctionnalite(icone, titre, description, couleur, page, disabled=False):
    """Affiche une carte de fonctionnalité élégante"""
    style = f"""
        <div style="
            background: {couleur if not disabled else '#cccccc'};
            padding: 2rem;
            border-radius: 20px;
            text-align: center;
            color: white;
            margin-bottom: 1rem;
            cursor: {'pointer' if not disabled else 'not-allowed'};
            transition: all 0.3s ease;
            box-shadow: 0 10px 20px rgba(0,0,0,0.1);
            opacity: {1 if not disabled else 0.5};
        ">
            <div style="font-size: 3.5rem; margin-bottom: 1rem;">{icone}</div>
            <div style="font-size: 1.5rem; font-weight: bold; margin-bottom: 0.5rem;">{titre}</div>
            <div style="font-size: 0.9rem; opacity: 0.9;">{description}</div>
        </div>
    """
    
    st.markdown(style, unsafe_allow_html=True)
    
    if not disabled:
        if st.button(f"📌 {titre}", key=f"btn_{page}", use_container_width=True):
            aller_a(page)

def afficher_tableau_de_bord():
    """Affiche le tableau de bord des exports avec style"""
    st.markdown("### 📊 Tableau de bord")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
            <div class="metric-card">
                <div style="font-size: 2rem;">📦</div>
                <div style="font-size: 1.2rem; font-weight: 600;">Total exports</div>
                <div style="font-size: 2rem; font-weight: 700;">{}</div>
            </div>
        """.format(st.session_state.tableau_de_bord['total_exports']), unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
            <div class="metric-card">
                <div style="font-size: 2rem;">📊</div>
                <div style="font-size: 1.2rem; font-weight: 600;">Lignes exportées</div>
                <div style="font-size: 2rem; font-weight: 700;">{}</div>
            </div>
        """.format(st.session_state.tableau_de_bord['total_lignes_exportees']), unsafe_allow_html=True)
    
    with col3:
        formats = st.session_state.tableau_de_bord['formats_utilises']
        format_principal = max(formats.items(), key=lambda x: x[1])[0] if formats else "Aucun"
        st.markdown("""
            <div class="metric-card">
                <div style="font-size: 2rem;">📁</div>
                <div style="font-size: 1.2rem; font-weight: 600;">Format principal</div>
                <div style="font-size: 2rem; font-weight: 700;">{}</div>
            </div>
        """.format(format_principal), unsafe_allow_html=True)
    
    with col4:
        dernier = st.session_state.tableau_de_bord['dernier_export']
        dernier_format = dernier['format'] if dernier else "Aucun"
        st.markdown("""
            <div class="metric-card">
                <div style="font-size: 2rem;">⏱️</div>
                <div style="font-size: 1.2rem; font-weight: 600;">Dernier export</div>
                <div style="font-size: 2rem; font-weight: 700;">{}</div>
            </div>
        """.format(dernier_format), unsafe_allow_html=True)
    
    if st.session_state.historique_exports:
        st.markdown("### 📜 Historique des exports")
        
        historique_df = pd.DataFrame([
            {
                'Date': e['timestamp'].strftime('%d/%m/%Y %H:%M'),
                'Utilisateur': f"{e.get('avatar', '👤')} {e.get('utilisateur', '')}",
                'Fichier': e['nom_fichier'][:30] + "..." if len(e['nom_fichier']) > 30 else e['nom_fichier'],
                'Format': e['format'],
                'Lignes': e['lignes']
            } for e in reversed(st.session_state.historique_exports[-10:])
        ])
        
        st.dataframe(historique_df, use_container_width=True, hide_index=True)

def afficher_page_admin():
    """Page d'administration avec style"""
    st.markdown("### 👥 Gestion des utilisateurs")
    
    utilisateurs = charger_utilisateurs()
    
    # Afficher la liste des utilisateurs
    for id, infos in utilisateurs.items():
        col1, col2, col3, col4, col5 = st.columns([1, 2, 2, 2, 1])
        
        with col1:
            st.markdown(f"""
                <div class="avatar-circle" style="background: {infos.get('couleur', '#667eea')}; width: 40px; height: 40px; font-size: 1.5rem;">
                    {infos.get('avatar', '👤')}
                </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"**{infos['nom']}**<br>*@{id}*", unsafe_allow_html=True)
        
        with col3:
            role = infos['role']
            badge = "🛡️ Admin" if role == "admin" else "👤 User"
            st.markdown(badge)
        
        with col4:
            if infos.get('derniere_connexion'):
                date = datetime.fromisoformat(infos['derniere_connexion']).strftime('%d/%m/%Y')
                st.markdown(f"📅 {date}")
            else:
                st.markdown("📅 Jamais")
        
        with col5:
            if id != st.session_state.identifiant and st.session_state.role == "admin":
                if st.button("🗑️", key=f"del_{id}"):
                    st.warning("Fonctionnalité à implémenter")
        
        st.markdown("---")
    
    # Formulaire de création d'utilisateur
    with st.expander("➕ Créer un nouvel utilisateur", expanded=False):
        with st.form("creation_utilisateur"):
            col1, col2 = st.columns(2)
            with col1:
                new_id = st.text_input("Identifiant")
                new_mdp = st.text_input("Mot de passe", type="password")
            with col2:
                new_nom = st.text_input("Nom complet")
                new_mdp_confirm = st.text_input("Confirmer", type="password")
            
            new_role = st.selectbox("Rôle", ["user", "admin"])
            
            if st.form_submit_button("✨ Créer l'utilisateur", use_container_width=True):
                if new_mdp != new_mdp_confirm:
                    st.error("❌ Les mots de passe ne correspondent pas")
                elif len(new_mdp) < 6:
                    st.error("❌ Le mot de passe doit faire au moins 6 caractères")
                else:
                    success, message = creer_utilisateur(new_id, new_nom, new_mdp, new_role)
                    if success:
                        st.success(f"✅ {message}")
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")

# ============================================================================
# PAGES DE L'APPLICATION
# ============================================================================

# Appliquer le style global
appliquer_style()

# ----------------------------------------------------------------------------
# PAGE DE CONNEXION
# ----------------------------------------------------------------------------
if not st.session_state.authentifie:
    # CSS spécifique à la page de connexion
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
        }
        .login-card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            padding: 3rem;
            border-radius: 30px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 450px;
            margin: 2rem auto;
            border: 1px solid rgba(255,255,255,0.2);
        }
        .login-title {
            text-align: center;
            margin-bottom: 2rem;
        }
        .login-title h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #FF6B6B 0%, #4ECDC4 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        .login-title p {
            color: #666;
            font-size: 1rem;
        }
        .feature-badge {
            background: #f8f9fa;
            padding: 0.5rem 1rem;
            border-radius: 50px;
            display: inline-block;
            margin: 0.25rem;
            font-size: 0.9rem;
            color: #333;
        }
        .demo-account {
            background: linear-gradient(135deg, #FF6B6B10 0%, #4ECDC410 100%);
            padding: 1rem;
            border-radius: 15px;
            margin: 1rem 0;
            border: 1px solid #FF6B6B20;
        }
        </style>
    """, unsafe_allow_html=True)
    
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("""
                <div class="login-card">
                    <div class="login-title">
                        <h1>🎯 GestLead Pro</h1>
                        <p>Gérez vos leads comme un professionnel</p>
                    </div>
            """, unsafe_allow_html=True)
            
            tab1, tab2 = st.tabs(["🔑 Connexion", "✨ Fonctionnalités"])
            
            with tab1:
                with st.form("login_form"):
                    st.markdown("#### Bienvenue !")
                    identifiant = st.text_input("Identifiant", placeholder="Entrez votre identifiant")
                    mot_de_passe = st.text_input("Mot de passe", type="password", placeholder="Entrez votre mot de passe")
                    
                    submitted = st.form_submit_button("🚀 SE CONNECTER", use_container_width=True)
                    
                    if submitted:
                        if identifiant and mot_de_passe:
                            success, resultat = authentifier(identifiant, mot_de_passe)
                            if success:
                                se_connecter(identifiant, resultat)
                                st.rerun()
                            else:
                                st.error(f"❌ {resultat}")
                        else:
                            st.warning("⚠️ Veuillez remplir tous les champs")
            
            with tab2:
                st.markdown("""
                    <div style="text-align: center;">
                        <p style="font-size: 3rem; margin-bottom: 1rem;">📊</p>
                        <h4>Fonctionnalités principales</h4>
                        <div style="margin: 1rem 0;">
                            <span class="feature-badge">📂 Import CSV/Excel</span>
                            <span class="feature-badge">📞 Formatage téléphone</span>
                            <span class="feature-badge">🗑️ Suppression doublons</span>
                            <span class="feature-badge">🔍 Filtrage intelligent</span>
                            <span class="feature-badge">💾 Export multi-format</span>
                            <span class="feature-badge">📊 Tableau de bord</span>
                            <span class="feature-badge">👥 Multi-utilisateurs</span>
                            <span class="feature-badge">🔄 Historique</span>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# PAGE D'ACCUEIL
# ----------------------------------------------------------------------------
elif st.session_state.page == "accueil":
    afficher_barre_laterale()
    
    # Bannière de bienvenue personnalisée
    st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {st.session_state.couleur} 0%, #4ECDC4 100%);
            padding: 2rem 3rem;
            border-radius: 30px;
            color: white;
            margin-bottom: 2rem;
            box-shadow: 0 20px 40px rgba(0,0,0,0.2);
        ">
            <div style="display: flex; align-items: center; gap: 2rem;">
                <div style="font-size: 4rem;">{st.session_state.avatar}</div>
                <div>
                    <div style="font-size: 2.5rem; font-weight: bold;">Bonjour {st.session_state.utilisateur} !</div>
                    <div style="font-size: 1.2rem; opacity: 0.9;">Prêt à gérer vos contacts ?</div>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # Tableau de bord
    afficher_tableau_de_bord()
    
    # Page admin
    if st.session_state.role == "admin":
        with st.expander("🛡️ Administration", expanded=False):
            afficher_page_admin()
    
    st.markdown("---")
    st.markdown("### 🚀 Modules disponibles")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        afficher_carte_fonctionnalite(
            "📂", "IMPORT", "Charger vos fichiers", 
            "#3498db", "import"
        )
    
    with col2:
        disabled = st.session_state.df_original is None
        afficher_carte_fonctionnalite(
            "📞", "TÉLÉPHONE", "Formater les numéros", 
            "#2ecc71", "telephone", disabled
        )
    
    with col3:
        disabled = st.session_state.df_original is None
        afficher_carte_fonctionnalite(
            "🗑️", "DOUBLONS", "Nettoyer les données", 
            "#e74c3c", "doublons", disabled
        )
    
    with col4:
        disabled = st.session_state.df_original is None
        afficher_carte_fonctionnalite(
            "🔍", "FILTRE", "Filtrer intelligemment", 
            "#f39c12", "filtre", disabled
        )
    
    col1, col2, col3 = st.columns(3)
    with col2:
        disabled = st.session_state.df_original is None
        if st.button("💾 EXPORTER", key="btn_export", disabled=disabled, use_container_width=True, type="primary"):
            aller_a("export")
    
    # Pied de page
    st.markdown("""
        <div class="footer">
            <p>© 2024 GestLead Pro - Tous droits réservés</p>
            <p style="font-size: 0.8rem;">Version 2.0 - Interface moderne</p>
        </div>
    """, unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# AUTRES PAGES (à compléter avec le code existant des modules)
# ----------------------------------------------------------------------------
elif st.session_state.page == "import":
    st.title("📂 Module Import")
    st.info("🚧 Module en cours de développement...")
    if st.button("← Retour"):
        aller_a("accueil")

elif st.session_state.page == "telephone":
    st.title("📞 Module Téléphone")
    st.info("🚧 Module en cours de développement...")
    if st.button("← Retour"):
        aller_a("accueil")

elif st.session_state.page == "doublons":
    st.title("🗑️ Module Doublons")
    st.info("🚧 Module en cours de développement...")
    if st.button("← Retour"):
        aller_a("accueil")

elif st.session_state.page == "filtre":
    st.title("🔍 Module Filtre")
    st.info("🚧 Module en cours de développement...")
    if st.button("← Retour"):
        aller_a("accueil")

elif st.session_state.page == "export":
    st.title("💾 Module Export")
    st.info("🚧 Module en cours de développement...")
    if st.button("← Retour"):
        aller_a("accueil")