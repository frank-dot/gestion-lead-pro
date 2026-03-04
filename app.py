import streamlit as st
import pandas as pd
import re
from datetime import datetime
from collections import Counter
import io
import json
import os
import hashlib

# ============================================================================
# CONFIGURATION INITIALE
# ============================================================================
st.set_page_config(
    page_title="Gestion Contacts Pro",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================================
# AUTHENTIFICATION PAR MOT DE PASSE
# ============================================================================
FICHIER_UTILISATEURS = "utilisateurs.json"

def hash_password(mot_de_passe):
    """Hash un mot de passe avec SHA256"""
    return hashlib.sha256(mot_de_passe.encode()).hexdigest()

def charger_utilisateurs():
    """Charge les utilisateurs depuis le fichier JSON"""
    if os.path.exists(FICHIER_UTILISATEURS):
        try:
            with open(FICHIER_UTILISATEURS, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def sauvegarder_utilisateurs(utilisateurs):
    """Sauvegarde les utilisateurs dans le fichier JSON"""
    with open(FICHIER_UTILISATEURS, 'w', encoding='utf-8') as f:
        json.dump(utilisateurs, f, indent=2, ensure_ascii=False)

def creer_utilisateur_defaut():
    """Crée un utilisateur admin par défaut si aucun n'existe"""
    utilisateurs = charger_utilisateurs()
    if not utilisateurs:
        utilisateurs["admin"] = {
            "nom": "Administrateur",
            "mot_de_passe": hash_password("admin123"),
            "role": "admin",
            "date_creation": datetime.now().isoformat()
        }
        sauvegarder_utilisateurs(utilisateurs)
    return utilisateurs

def authentifier(identifiant, mot_de_passe):
    """Vérifie les identifiants de connexion"""
    utilisateurs = charger_utilisateurs()
    
    if identifiant in utilisateurs:
        if utilisateurs[identifiant]["mot_de_passe"] == hash_password(mot_de_passe):
            return True, utilisateurs[identifiant]
    
    return False, None

# ============================================================================
# INITIALISATION DE LA SESSION
# ============================================================================
def init_session_state():
    """Initialise toutes les variables de session au démarrage"""
    defaults = {
        'authentifie': False,
        'page': 'login',
        'nom': '',
        'identifiant': '',
        'role': 'user',
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
        'taille_ko': 0
    }
    
    st.session_state.historique_exports.append(export)
    
    # Mettre à jour le tableau de bord
    st.session_state.tableau_de_bord['total_exports'] += 1
    st.session_state.tableau_de_bord['total_lignes_exportees'] += lignes
    st.session_state.tableau_de_bord['formats_utilises'][format_export] = st.session_state.tableau_de_bord['formats_utilises'].get(format_export, 0) + 1
    st.session_state.tableau_de_bord['dernier_export'] = export

def se_connecter(identifiant, user_info):
    """Gère la connexion"""
    st.session_state.authentifie = True
    st.session_state.nom = user_info.get("nom", identifiant)
    st.session_state.identifiant = identifiant
    st.session_state.role = user_info.get("role", "user")
    st.session_state.page = "accueil"

def se_deconnecter():
    """Gère la déconnexion"""
    st.session_state.authentifie = False
    st.session_state.page = "login"
    st.session_state.nom = ''
    st.session_state.identifiant = ''
    st.session_state.role = 'user'
    st.session_state.df_original = None
    st.session_state.df_travail = None
    st.session_state.nom_fichier = ''
    st.session_state.historique_actions = []
    st.session_state.position_historique = -1

def sauvegarder_session():
    """Sauvegarde la session dans un fichier JSON"""
    session_data = {
        'nom': st.session_state.nom,
        'identifiant': st.session_state.identifiant,
        'role': st.session_state.role,
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
        st.session_state.nom = data.get('nom', 'Utilisateur')
        st.success(f"✅ Session chargée: {data.get('date_sauvegarde', '')}")
        return True
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
# COMPOSANTS D'INTERFACE RÉUTILISABLES
# ============================================================================
def afficher_barre_laterale():
    """Affiche la barre latérale avec les infos utilisateur"""
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/user-male-circle.png", width=80)
        st.markdown(f"### 👤 {st.session_state.get('nom', 'Utilisateur')}")
        if st.session_state.get('identifiant'):
            st.markdown(f"*@{st.session_state.identifiant}*")
        
        st.markdown("---")
        st.markdown(f"📅 {datetime.now().strftime('%d/%m/%Y')}")
        st.markdown(f"⏰ {datetime.now().strftime('%H:%M')}")
        
        if st.session_state.df_original is not None:
            st.markdown("---")
            st.markdown("**📁 Fichier actuel :**")
            st.markdown(f"*{st.session_state.nom_fichier}*")
            st.markdown(f"*{len(st.session_state.df_original)} lignes*")
            
            if len(st.session_state.historique_actions) > 1:
                st.markdown("---")
                st.markdown("**🔄 Historique des actions**")
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
        st.markdown("**💾 Sauvegarde**")
        
        if st.button("📥 Sauvegarder la session", use_container_width=True):
            session_json = sauvegarder_session()
            st.download_button(
                label="📥 Télécharger la sauvegarde",
                data=session_json,
                file_name=f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )
        
        uploaded_session = st.file_uploader("Charger une session", type=['json'], key="session_upload")
        if uploaded_session is not None:
            session_data = uploaded_session.read().decode('utf-8')
            if charger_session(session_data):
                st.success("✅ Session chargée!")
        
        st.markdown("---")
        if st.button("🚪 Se déconnecter", use_container_width=True):
            se_deconnecter()
            st.rerun()

def afficher_carte_fonctionnalite(icone, titre, couleur, page, disabled=False):
    """Affiche une carte de fonctionnalité cliquable"""
    style = f"""
        background: {couleur};
        padding: 1.5rem;
        border-radius: 10px;
        text-align: center;
        color: white;
        margin-bottom: 1rem;
        opacity: {0.5 if disabled else 1};
        cursor: pointer;
        transition: transform 0.3s;
    """
    
    st.markdown(f"""
        <div style="{style}">
            <div style="font-size: 3rem;">{icone}</div>
            <div style="font-size: 1.3rem; font-weight: bold;">{titre}</div>
        </div>
    """, unsafe_allow_html=True)
    
    if not disabled:
        if st.button(f"📌 {titre}", key=f"btn_{page}", use_container_width=True):
            aller_a(page)

def afficher_tableau_de_bord():
    """Affiche le tableau de bord des exports"""
    st.subheader("📊 Tableau de bord des exports")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total exports", st.session_state.tableau_de_bord['total_exports'])
    with col2:
        st.metric("Lignes exportées", st.session_state.tableau_de_bord['total_lignes_exportees'])
    with col3:
        formats = st.session_state.tableau_de_bord['formats_utilises']
        format_principal = max(formats.items(), key=lambda x: x[1])[0] if formats else "Aucun"
        st.metric("Format principal", format_principal)
    with col4:
        if st.session_state.tableau_de_bord['dernier_export']:
            dernier = st.session_state.tableau_de_bord['dernier_export']
            st.metric("Dernier export", dernier['format'])

def afficher_gestion_utilisateurs():
    """Affiche l'interface de gestion des utilisateurs"""
    st.subheader("👥 Gestion des utilisateurs")
    
    utilisateurs = charger_utilisateurs()
    
    # Afficher la liste des utilisateurs existants
    st.write("### Utilisateurs existants")
    
    for identifiant, infos in utilisateurs.items():
        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        with col1:
            st.write(f"**{infos['nom']}**")
        with col2:
            st.write(f"@{identifiant}")
        with col3:
            role = "🛡️ Admin" if infos['role'] == 'admin' else "👤 User"
            st.write(role)
        with col4:
            if identifiant != "admin":  # Ne pas pouvoir supprimer admin
                if st.button("🗑️", key=f"del_{identifiant}"):
                    del utilisateurs[identifiant]
                    sauvegarder_utilisateurs(utilisateurs)
                    st.rerun()
        st.markdown("---")
    
    # Formulaire d'ajout
    with st.expander("➕ Ajouter un nouvel utilisateur"):
        with st.form("form_ajout_utilisateur"):
            new_id = st.text_input("Identifiant")
            new_nom = st.text_input("Nom complet")
            new_mdp = st.text_input("Mot de passe", type="password")
            new_mdp2 = st.text_input("Confirmer mot de passe", type="password")
            new_role = st.selectbox("Rôle", ["user", "admin"])
            
            if st.form_submit_button("Créer l'utilisateur"):
                if not new_id or not new_nom or not new_mdp:
                    st.error("Tous les champs sont requis")
                elif new_mdp != new_mdp2:
                    st.error("Les mots de passe ne correspondent pas")
                elif len(new_mdp) < 4:
                    st.error("Le mot de passe doit faire au moins 4 caractères")
                else:
                    utilisateurs = charger_utilisateurs()
                    if new_id in utilisateurs:
                        st.error("Cet identifiant existe déjà")
                    else:
                        utilisateurs[new_id] = {
                            "nom": new_nom,
                            "mot_de_passe": hash_password(new_mdp),
                            "role": new_role,
                            "date_creation": datetime.now().isoformat()
                        }
                        sauvegarder_utilisateurs(utilisateurs)
                        st.success(f"✅ Utilisateur {new_id} créé avec succès")
                        st.rerun()    
    # Historique des exports
    if st.session_state.historique_exports:
        st.subheader("📜 Historique des exports")
        
        # Créer un DataFrame pour l'affichage
        historique_df = pd.DataFrame([
            {
                'Date': e['timestamp'].strftime('%d/%m/%Y %H:%M'),
                'Utilisateur': e.get('utilisateur', ''),
                'Fichier': e['nom_fichier'],
                'Format': e['format'],
                'Lignes': e['lignes'],
                'Colonnes': e['colonnes'],
                'Source': e['fichier_source']
            } for e in reversed(st.session_state.historique_exports[-20:])
        ])
        
        st.dataframe(historique_df, use_container_width=True)
        
        # Statistiques
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"📊 Moyenne de lignes par export: {st.session_state.tableau_de_bord['total_lignes_exportees'] / max(1, st.session_state.tableau_de_bord['total_exports']):.0f}")
        with col2:
            st.info(f"📁 Formats utilisés: {', '.join([f'{k}: {v}' for k, v in st.session_state.tableau_de_bord['formats_utilises'].items()])}")

# ============================================================================
# PAGES DE L'APPLICATION
# ============================================================================

# ----------------------------------------------------------------------------
# PAGE DE CONNEXION MODERNE
# ----------------------------------------------------------------------------
if st.session_state.page == "login":
    # Créer l'utilisateur par défaut au premier lancement
    creer_utilisateur_defaut()
    
    st.markdown("""
        <style>
        .stApp {
            background: linear-gradient(145deg, #4158D0 0%, #C850C0 46%, #FFCC70 100%);
            font-family: 'Poppins', sans-serif;
        }
        
        .login-card {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.2);
            padding: 3rem 2.5rem;
            width: 100%;
            max-width: 450px;
            margin: 3rem auto;
            animation: fadeIn 0.5s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .login-header {
            text-align: center;
            margin-bottom: 2.5rem;
        }
        
        .login-header h1 {
            font-size: 2.2rem;
            font-weight: 700;
            background: linear-gradient(145deg, #4158D0 0%, #C850C0 46%, #FFCC70 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        
        .login-header p {
            color: #888;
            font-size: 0.95rem;
        }
        
        .input-group {
            margin-bottom: 1.5rem;
        }
        
        .input-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: #fffff;
            font-weight: 500;
            font-size: 0.95rem;
        }
        
        .input-group input {
            width: 100%;
            padding: 0.9rem 1rem;
            border: 2px solid #e0e0e0;
            border-radius: 12px;
            font-size: 1rem;
            transition: all 0.3s ease;
            outline: none;
        }
        
        .input-group input:focus {
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }
        
        .input-group input::placeholder {
            color: #bbb;
            font-size: 0.95rem;
        }
        
        .checkbox-group {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 1rem 0 2rem 0;
        }
        
        .checkbox-label {
            display: flex;
            align-items: center;
            color: #fffff;
            font-size: 0.95rem;
            cursor: pointer;
        }
        
        .checkbox-label input {
            margin-right: 0.5rem;
            accent-color: #667eea;
            width: 18px;
            height: 18px;
        }
        
        .forgot-link {
            color: #667eea;
            text-decoration: none;
            font-size: 0.95rem;
            font-weight: 500;
            transition: color 0.3s ease;
        }
        
        .forgot-link:hover {
            color: #764ba2;
            text-decoration: underline;
        }
        
        .login-btn {
            width: 100%;
            padding: 1rem;
            background: linear-gradient(145deg, #4158D0 0%, #C850C0 46%, #FFCC70 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 10px 20px rgba(102,126,234,0.3);
            margin-bottom: 1.5rem;
        }
        
        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 30px rgba(102,126,234,0.4);
        }
        
        .login-btn:active {
            transform: translateY(0);
        }
        
        .demo-info {
            text-align: center;
            padding: 1rem;
            background: linear-gradient(145deg, #4158D0 0%, #C850C0 46%, #FFCC70 100%);
            border-radius: 12px;
            border: 1px dashed #667eea;
        }
        
        .demo-info p {
            margin: 0.3rem 0;
            color: #666;
            font-size: 0.9rem;
        }
        
        .demo-info code {
            background: #e9ecef;
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            color: #667eea;
            font-weight: 600;
        }
        
        .footer-text {
            text-align: center;
            margin-top: 2rem;
            color: #FFFFFF;
            font-size: 0.85rem;
        }
        </style>
    """, unsafe_allow_html=True)
    
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("""
                <div class="login-card">
                    <div class="login-header">
                        <h1>🔐 Gestion Leads Pro</h1>
                        <p>Connectez-vous pour accéder à votre espace</p>
                    </div>
            """, unsafe_allow_html=True)
            
            with st.form("login_form"):
                # Champ Username
                st.markdown("""
                    <div class="input-group">
                        <label>Username</label>
                    </div>
                """, unsafe_allow_html=True)
                identifiant = st.text_input(" ", placeholder="Entrez votre identifiant", label_visibility="collapsed")
                
                # Champ Password
                st.markdown("""
                    <div class="input-group">
                        <label>Password</label>
                    </div>
                """, unsafe_allow_html=True)
                mot_de_passe = st.text_input(" ", type="password", placeholder="Entrez votre mot de passe", label_visibility="collapsed")
                
                # Remember me & Forgot Password
                st.markdown("""
                    <div class="checkbox-group">
                        <label class="checkbox-label">
                            <input type="checkbox"> Remember me
                        </label>
                        <a href="#" class="forgot-link">Forget Password?</a>
                    </div>
                """, unsafe_allow_html=True)
                
                # Bouton Login
                submitted = st.form_submit_button("LOGIN", use_container_width=True)
                
                if submitted:
                    if identifiant and mot_de_passe:
                        success, user_info = authentifier(identifiant, mot_de_passe)
                        if success:
                            se_connecter(identifiant, user_info)
                            st.rerun()
                        else:
                            st.error("❌ Identifiant ou mot de passe incorrect")
                    else:
                        st.warning("⚠️ Veuillez remplir tous les champs")
            
            # Informations de démo
            st.markdown("""
                
                <div class="footer-text">
                    © 2026 AETECH SOLUTIONS SARL. Tous droits réservés.
                </div>
            """, unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
# ----------------------------------------------------------------------------
# PAGE D'ACCUEIL
# ----------------------------------------------------------------------------
elif st.session_state.page == "accueil":
    afficher_barre_laterale()
    
    st.markdown("""
        <style>
        .welcome-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 2rem;
            border-radius: 10px;
            color: white;
            margin-bottom: 2rem;
        }
        .welcome-title {
            font-size: 2.5rem;
            font-weight: bold;
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
        <div class="welcome-header">
            <div class="welcome-title">📋 Bienvenue {st.session_state.nom} !</div>
        </div>
    """, unsafe_allow_html=True)
    
    # Tableau de bord
    afficher_tableau_de_bord()
    
    # Gestion des utilisateurs (visible seulement pour admin)
    if st.session_state.role == "admin":
        with st.expander("🛡️ Administration - Gestion des utilisateurs", expanded=False):
            afficher_gestion_utilisateurs()
    
    st.markdown("---")
    st.subheader("🚀 Modules disponibles")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        afficher_carte_fonctionnalite("📂", "IMPORT", "#3498db", "import")
    
    with col2:
        disabled = st.session_state.df_original is None
        afficher_carte_fonctionnalite("📞", "TÉLÉPHONE", "#2ecc71", "telephone", disabled)
    
    with col3:
        disabled = st.session_state.df_original is None
        afficher_carte_fonctionnalite("🗑️", "DOUBLONS", "#e74c3c", "doublons", disabled)
    
    with col4:
        disabled = st.session_state.df_original is None
        afficher_carte_fonctionnalite("🔍", "FILTRE", "#f39c12", "filtre", disabled)
    
    col1, col2, col3 = st.columns(3)
    with col2:
        disabled = st.session_state.df_original is None
        if st.button("💾 EXPORTER", key="btn_export", disabled=disabled, use_container_width=True, type="primary"):
            aller_a("export")
# ----------------------------------------------------------------------------
# PAGE IMPORT
# ----------------------------------------------------------------------------
elif st.session_state.page == "import":
    st.title("📂 Import de fichier")
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            aller_a("accueil")
    
    st.markdown("---")
    
    uploaded_file = st.file_uploader("Choisir un fichier CSV ou Excel", type=['csv', 'xlsx'])
    
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                mode = st.radio(
                    "Mode d'import",
                    ["🔍 Auto-détection", "✋ Manuel"],
                    horizontal=True
                )
                
                if mode == "🔍 Auto-détection":
                    with st.spinner("🔍 Détection automatique en cours..."):
                        enc, sep = detecter_encodage_et_separateur(uploaded_file)
                        
                        if enc and sep:
                            st.success("✅ Détection réussie!")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                st.info(f"📌 Encodage détecté: **{enc}**")
                            with col2:
                                sep_text = "Virgule (,)" if sep == ',' else "Point-virgule (;)" if sep == ';' else "Tabulation"
                                st.info(f"📌 Séparateur détecté: **{sep_text}**")
                            
                            uploaded_file.seek(0)
                            df = pd.read_csv(uploaded_file, sep=sep, encoding=enc)
                        else:
                            st.error("❌ Détection automatique échouée")
                            st.info("Passez en mode manuel")
                            st.stop()
                
                else:
                    col1, col2 = st.columns(2)
                    with col1:
                        sep_choice = st.radio("Séparateur", ["Virgule (,)", "Point-virgule (;)"])
                    with col2:
                        enc_choice = st.radio("Encodage", ["latin1", "cp1252", "utf-8"])
                    
                    sep_char = ',' if sep_choice == "Virgule (,)" else ';'
                    
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, sep=sep_char, encoding=enc_choice)
            
            else:
                df = pd.read_excel(uploaded_file)
            
            a_doublons, doublons = verifier_colonnes_en_double(df)
            if a_doublons:
                st.warning(f"⚠️ Colonnes en double: {', '.join(doublons)}")
                if st.button("🔄 Renommer"):
                    df = renommer_colonnes_doublons(df)
                    st.success("✅ Colonnes renommées!")
            
            st.session_state.df_original = df.copy()
            st.session_state.df_travail = df.copy()
            st.session_state.nom_fichier = uploaded_file.name
            sauvegarder_etat(df)
            
            st.success(f"✅ Fichier chargé: {len(df)} lignes, {len(df.columns)} colonnes")
            st.dataframe(df.head(10), use_container_width=True)
            
            with st.expander("📋 Voir toutes les colonnes"):
                st.write(df.columns.tolist())
            
            if st.button("✅ VALIDER", use_container_width=True, type="primary"):
                aller_a("accueil")
            
        except Exception as e:
            st.error(f"❌ Erreur: {e}")
            st.info("💡 En mode manuel, essayez latin1 avec point-virgule")

# ----------------------------------------------------------------------------
# PAGE TÉLÉPHONE
# ----------------------------------------------------------------------------
elif st.session_state.page == "telephone":
    st.title("📞 Module Téléphone")
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            aller_a("accueil")
    
    st.markdown("---")
    
    if st.session_state.df_travail is not None:
        df = st.session_state.df_travail.copy()
        
        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            st.subheader("1. Choisir la colonne")
            
            cols_tel = [col for col in df.columns if any(
                x in col.lower() for x in ['tel', 'phone', 'mobile', 'téléphone', 'telephone']
            )]
            if not cols_tel:
                cols_tel = df.columns.tolist()
            
            col_telephone = st.selectbox("Colonne des téléphones", cols_tel)
            
            st.subheader("2. Choisir le format")
            format_tel = st.radio(
                "Format souhaité",
                ["33 (ex: 33612345678)", "0 (ex: 0612345678)", "Garder chiffres seuls"],
                horizontal=True
            )
            
            if st.button("🔧 APPLIQUER LE FORMATAGE", use_container_width=True, type="primary"):
                format_map = {
                    "33 (ex: 33612345678)": "33",
                    "0 (ex: 0612345678)": "0",
                    "Garder chiffres seuls": "garde"
                }
                
                st.session_state.df_travail[col_telephone] = df[col_telephone].apply(
                    lambda x: formater_telephone(x, format_map[format_tel])
                )
                sauvegarder_etat(st.session_state.df_travail)
                st.success("✅ Téléphones formatés!")
                st.rerun()
        
        with col_right:
            st.subheader("Aperçu avant/après")
            
            aperçu = df[[col_telephone]].head(10).copy()
            format_map = {
                "33 (ex: 33612345678)": "33",
                "0 (ex: 0612345678)": "0",
                "Garder chiffres seuls": "garde"
            }
            
            aperçu['Après formatage'] = aperçu[col_telephone].apply(
                lambda x: formater_telephone(x, format_map[format_tel])
            )
            
            st.dataframe(aperçu, use_container_width=True)
            
            st.subheader("Statistiques")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total lignes", len(df))
            with col2:
                non_vides = df[col_telephone].notna().sum()
                st.metric("Téléphones présents", non_vides)
    
    else:
        st.warning("⚠️ Aucun fichier chargé. Veuillez d'abord importer un fichier.")

# ----------------------------------------------------------------------------
# PAGE DOUBLONS
# ----------------------------------------------------------------------------
elif st.session_state.page == "doublons":
    st.title("🗑️ Module Doublons")
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            aller_a("accueil")
    
    st.markdown("---")
    
    if st.session_state.df_travail is not None:
        df = st.session_state.df_travail.copy()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Lignes totales", len(df))
        with col2:
            doublons_exacts = df.duplicated().sum()
            st.metric("Doublons exacts", doublons_exacts)
        with col3:
            lignes_uniques = len(df) - doublons_exacts
            st.metric("Lignes uniques", lignes_uniques)
        
        st.markdown("---")
        
        tab1, tab2 = st.tabs(["🔍 DOUBLONS EXACTS", "🎯 DOUBLONS SUR COLONNE"])
        
        with tab1:
            st.subheader("Supprimer les lignes strictement identiques")
            
            if doublons_exacts > 0:
                st.warning(f"⚠️ {doublons_exacts} doublons exacts détectés")
                
                if st.checkbox("Voir les doublons"):
                    doublons_df = df[df.duplicated(keep=False)].sort_values(by=df.columns[0])
                    st.dataframe(doublons_df, use_container_width=True)
                
                if st.button("🗑️ SUPPRIMER LES DOUBLONS EXACTS", use_container_width=True, type="primary"):
                    avant = len(st.session_state.df_travail)
                    st.session_state.df_travail = st.session_state.df_travail.drop_duplicates()
                    apres = len(st.session_state.df_travail)
                    sauvegarder_etat(st.session_state.df_travail)
                    st.success(f"✅ {avant - apres} doublons supprimés! {apres} lignes restantes")
                    st.rerun()
            else:
                st.success("✅ Aucun doublon exact détecté")
        
        with tab2:
            st.subheader("Supprimer les doublons basés sur une colonne spécifique")
            
            col_doublons = st.selectbox("Choisir la colonne", df.columns)
            
            doublons_col = df.duplicated(subset=[col_doublons]).sum()
            valeurs_doublons = df[col_doublons].value_counts()
            valeurs_doublons = valeurs_doublons[valeurs_doublons > 1]
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric(f"Doublons sur '{col_doublons}'", doublons_col)
            with col2:
                st.metric("Valeurs en double", len(valeurs_doublons))
            
            if not valeurs_doublons.empty:
                with st.expander("Voir les valeurs en double"):
                    st.dataframe(valeurs_doublons, use_container_width=True)
                
                if st.button(f"🗑️ SUPPRIMER DOUBLONS SUR '{col_doublons}'", use_container_width=True, type="primary"):
                    avant = len(st.session_state.df_travail)
                    st.session_state.df_travail = st.session_state.df_travail.drop_duplicates(subset=[col_doublons])
                    apres = len(st.session_state.df_travail)
                    sauvegarder_etat(st.session_state.df_travail)
                    st.success(f"✅ {avant - apres} doublons supprimés! {apres} lignes restantes")
                    st.rerun()
            else:
                st.success(f"✅ Aucun doublon sur la colonne '{col_doublons}'")
        
        st.markdown("---")
        st.subheader("Aperçu du fichier actuel")
        st.dataframe(st.session_state.df_travail.head(10), use_container_width=True)
    
    else:
        st.warning("⚠️ Aucun fichier chargé. Veuillez d'abord importer un fichier.")

# ----------------------------------------------------------------------------
# PAGE FILTRE UNIVERSEL
# ----------------------------------------------------------------------------
elif st.session_state.page == "filtre":
    st.title("🔍 Module Filtre Universel")
    st.markdown("Filtrez vos données sur n'importe quelle colonne avec des règles intelligentes")
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            aller_a("accueil")
    
    st.markdown("---")
    
    if st.session_state.df_travail is not None:
        df = st.session_state.df_travail.copy()
        
        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            st.subheader("1. Choisir la colonne à filtrer")
            
            col_filtre = st.selectbox(
                "Colonne à filtrer",
                df.columns.tolist(),
                key="col_filtre_universel"
            )
            
            with st.expander(f"📋 Voir les valeurs uniques de '{col_filtre}'"):
                valeurs_uniques = df[col_filtre].dropna().astype(str).unique()
                nb_uniques = len(valeurs_uniques)
                st.write(f"**{nb_uniques} valeurs uniques**")
                st.write(sorted(valeurs_uniques)[:50])
                if nb_uniques > 50:
                    st.caption(f"... et {nb_uniques - 50} autres")
            
            st.markdown("---")
            st.subheader("2. Choisir le mode de filtrage")
            
            mode_filtre = st.radio(
                "Mode",
                [
                    "📍 Code postal (règles spéciales)",
                    "🎯 Correspondance exacte",
                    "🔍 Contient le texte",
                    "📊 Filtre numérique",
                    "📝 Expression régulière"
                ],
                horizontal=True,
                key="mode_filtre"
            )
            
            if mode_filtre == "📍 Code postal (règles spéciales)":
                st.info("""
                **Règles spéciales pour les codes postaux :**
                - **06** = tous les codes qui commencent par 06
                - **75001** = code exact 75001
                - **75** = tous les codes qui commencent par 75
                """)
                
                # Option 1: Sélection par liste
                st.markdown("**Option 1 : Sélection dans la liste**")
                codes_disponibles = sorted(df[col_filtre].dropna().astype(str).unique())
                depts_disponibles = sorted(list(set([c[:2] for c in codes_disponibles if len(c) >= 2 and c[:2].isdigit()])))
                
                col1, col2 = st.columns(2)
                with col1:
                    depts_selection = st.multiselect("Départements", depts_disponibles)
                with col2:
                    codes_selection = st.multiselect("Codes exacts", codes_disponibles)
                
                # Option 2: Saisie manuelle
                st.markdown("**Option 2 : Saisie manuelle**")
                criteres_input = st.text_area(
                    " ",
                    placeholder="Exemples:\n06\n75\n75001\n91250",
                    height=100,
                    key="codes_input"
                )
                
                criteres_list = []
                criteres_list.extend(depts_selection)
                criteres_list.extend(codes_selection)
                
                if criteres_input:
                    lignes = criteres_input.strip().split('\n')
                    for ligne in lignes:
                        ligne = ligne.strip()
                        if ligne:
                            criteres_list.append(ligne)
                
                criteres_list = list(set(criteres_list))
                
                if criteres_list:
                    st.success(f"✅ {len(criteres_list)} critères: {', '.join(sorted(criteres_list))}")
                    
                    def filtre_code_postal(valeur):
                        if pd.isna(valeur):
                            return False
                        val_str = str(valeur).strip()
                        for critere in criteres_list:
                            critere = critere.strip()
                            if len(critere) <= 2 and critere.isdigit() and val_str.startswith(critere):
                                return True
                            elif len(critere) == 5 and critere.isdigit() and val_str == critere:
                                return True
                            elif val_str == critere:
                                return True
                        return False
                    
                    filtre_func = filtre_code_postal
            
            elif mode_filtre == "🎯 Correspondance exacte":
                st.markdown("**Option 1 : Sélection dans la liste**")
                valeurs_liste = sorted(df[col_filtre].dropna().astype(str).unique())
                selection_liste = st.multiselect("Choisir des valeurs", valeurs_liste)
                
                st.markdown("**Option 2 : Saisie manuelle**")
                criteres_input = st.text_area(
                    "Entrez les valeurs (une par ligne)",
                    placeholder="Exemples:\n4250Z\nCoiffeur\nParis",
                    height=100,
                    key="exact_input"
                )
                
                criteres_list = selection_liste.copy()
                if criteres_input:
                    lignes = criteres_input.strip().split('\n')
                    for ligne in lignes:
                        ligne = ligne.strip()
                        if ligne:
                            criteres_list.append(ligne)
                
                criteres_list = list(set(criteres_list))
                
                if criteres_list:
                    st.success(f"✅ {len(criteres_list)} critères")
                    
                    def filtre_exact(valeur):
                        if pd.isna(valeur):
                            return False
                        return str(valeur).strip() in criteres_list
                    
                    filtre_func = filtre_exact
            
            elif mode_filtre == "🔍 Contient le texte":
                criteres_input = st.text_area(
                    "Entrez les textes à rechercher (un par ligne)",
                    placeholder="Exemples:\nCoiffeur\nBoulanger\nRestaurant",
                    height=150,
                    key="contient_input"
                )
                
                if criteres_input:
                    criteres_list = [l.strip().lower() for l in criteres_input.strip().split('\n') if l.strip()]
                    st.success(f"✅ {len(criteres_list)} textes")
                    
                    def filtre_contient(valeur):
                        if pd.isna(valeur):
                            return False
                        val_str = str(valeur).lower()
                        for critere in criteres_list:
                            if critere in val_str:
                                return True
                        return False
                    
                    filtre_func = filtre_contient
            
            elif mode_filtre == "📊 Filtre numérique":
                if pd.api.types.is_numeric_dtype(df[col_filtre]):
                    min_val = float(df[col_filtre].min())
                    max_val = float(df[col_filtre].max())
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        seuil_min = st.number_input("Minimum", value=min_val)
                    with col2:
                        seuil_max = st.number_input("Maximum", value=max_val)
                    
                    exclure = st.checkbox("Exclure cette plage")
                    
                    if exclure:
                        def filtre_numerique(valeur):
                            if pd.isna(valeur):
                                return False
                            return not (seuil_min <= valeur <= seuil_max)
                    else:
                        def filtre_numerique(valeur):
                            if pd.isna(valeur):
                                return False
                            return seuil_min <= valeur <= seuil_max
                    
                    filtre_func = filtre_numerique
                else:
                    st.warning(f"⚠️ La colonne n'est pas numérique")
                    filtre_func = None
            
            elif mode_filtre == "📝 Expression régulière":
                regex = st.text_input(
                    "Expression régulière",
                    placeholder="Ex: ^06.*$",
                    key="regex_input"
                )
                
                if regex:
                    try:
                        pattern = re.compile(regex)
                        st.success("✅ Expression valide")
                        
                        def filtre_regex(valeur):
                            if pd.isna(valeur):
                                return False
                            return bool(pattern.search(str(valeur)))
                        
                        filtre_func = filtre_regex
                    except Exception as e:
                        st.error(f"❌ Expression invalide: {e}")
                        filtre_func = None
            else:
                filtre_func = None
            
            if 'filtre_func' in locals() and filtre_func is not None:
                st.markdown("---")
                
                try:
                    masque_filtre = df[col_filtre].apply(filtre_func)
                    nb_resultats = masque_filtre.sum()
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Contacts trouvés", nb_resultats)
                    with col2:
                        st.metric("Pourcentage", f"{nb_resultats/len(df)*100:.1f}%")
                    
                    if nb_resultats > 0:
                        if st.checkbox("👀 Voir l'aperçu"):
                            aperçu = df[masque_filtre].head(10)
                            st.dataframe(aperçu, use_container_width=True)
                        
                        if st.button("✅ CRÉER UN NOUVEAU FICHIER", use_container_width=True, type="primary"):
                            df_filtre = df[masque_filtre].copy()
                            st.session_state.df_travail = df_filtre
                            sauvegarder_etat(st.session_state.df_travail)
                            st.success(f"✅ Nouveau fichier créé avec {nb_resultats} contacts!")
                            st.rerun()
                    else:
                        st.warning("⚠️ Aucun contact trouvé")
                        
                except Exception as e:
                    st.error(f"Erreur: {e}")
        
        with col_right:
            st.subheader("Aperçu")
            echantillon = df[[col_filtre]].head(10)
            st.dataframe(echantillon, use_container_width=True)
            
            st.metric("Valeurs non vides", df[col_filtre].notna().sum())
            st.metric("Valeurs uniques", df[col_filtre].nunique())
    
    else:
        st.warning("⚠️ Aucun fichier chargé.")

# ----------------------------------------------------------------------------
# PAGE EXPORT
# ----------------------------------------------------------------------------
elif st.session_state.page == "export":
    st.title("💾 Module Export")
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour à l'accueil", use_container_width=True):
            aller_a("accueil")
    
    st.markdown("---")
    
    if st.session_state.df_travail is not None:
        df = st.session_state.df_travail.copy()
        
        st.info(f"📊 Fichier à exporter: **{len(df)}** lignes, **{len(df.columns)}** colonnes")
        
        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            st.subheader("1. Format d'export")
            format_export = st.radio(
                "Choisir le format",
                ["CSV", "Excel (.xlsx)", "JSON"],
                horizontal=True,
                key="format_export"
            )
            
            if format_export == "CSV":
                st.subheader("2. Options CSV")
                sep_csv = st.radio(
                    "Séparateur",
                    ["Point-virgule (;) - Pour Excel", "Virgule (,) - Standard"],
                    horizontal=True,
                    key="sep_csv"
                )
                sep = ';' if "Point-virgule" in sep_csv else ','
                
                encodage_csv = st.radio(
                    "Encodage",
                    ["latin1 (recommandé)", "utf-8"],
                    horizontal=True,
                    key="enc_csv"
                )
                enc = 'latin1' if "latin1" in encodage_csv else 'utf-8'
            
            elif format_export == "Excel (.xlsx)":
                st.subheader("2. Options Excel")
                inclure_resume = st.checkbox("Inclure une feuille de résumé", value=True)
                nom_feuille = st.text_input("Nom de la feuille principale", "Contacts")
            
            else:
                st.subheader("2. Options JSON")
                orientation_json = st.radio(
                    "Orientation",
                    ["records (liste)", "index (dictionnaire)", "table"],
                    horizontal=True,
                    key="orientation_json"
                )
            
            st.markdown("---")
            st.subheader("3. Colonnes à exporter")
            
            toutes_colonnes = st.checkbox("Toutes les colonnes", value=True, key="toutes_colonnes")
            
            if toutes_colonnes:
                colonnes_export = df.columns.tolist()
                st.success(f"✅ {len(colonnes_export)} colonnes sélectionnées")
            else:
                colonnes_export = st.multiselect(
                    "Choisir les colonnes",
                    df.columns.tolist(),
                    default=df.columns.tolist()[:5],
                    key="colonnes_export"
                )
                st.info(f"📌 {len(colonnes_export)} colonnes sélectionnées")
            
            st.markdown("---")
            st.subheader("4. Nom du fichier")
            
            nom_base = st.text_input(
                "Nom du fichier (sans extension)",
                value="contacts",
                key="nom_fichier_export"
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nom_complet = f"{nom_base}_{timestamp}"
            
            st.caption(f"Le fichier sera nommé: **{nom_complet}**")
            
            st.markdown("---")
            
            if st.button("📥 GÉNÉRER L'EXPORT", use_container_width=True, type="primary"):
                try:
                    df_export = df[colonnes_export].copy()
                    
                    if format_export == "CSV":
                        csv_data = df_export.to_csv(index=False, sep=sep, encoding=enc)
                        
                        # Enregistrer dans l'historique
                        taille_ko = len(csv_data.encode('utf-8')) / 1024
                        enregistrer_export(nom_complet + ".csv", "CSV", len(df_export), len(df_export.columns))
                        
                        st.download_button(
                            label="📥 Télécharger le fichier CSV",
                            data=csv_data,
                            file_name=f"{nom_complet}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
                        
                    elif format_export == "Excel (.xlsx)":
                        output = io.BytesIO()
                        
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df_export.to_excel(writer, index=False, sheet_name=nom_feuille[:31])
                            
                            if inclure_resume:
                                resume_data = {
                                    'Information': [
                                        "Date d'export",
                                        'Utilisateur',
                                        'Fichier source',
                                        'Lignes',
                                        'Colonnes',
                                        'Filtres appliqués',
                                        'Actions effectuées'
                                    ],
                                    'Valeur': [
                                        datetime.now().strftime('%d/%m/%Y %H:%M'),
                                        st.session_state.identifiant,
                                        st.session_state.nom_fichier,
                                        len(df_export),
                                        len(df_export.columns),
                                        'Oui' if len(df) != len(st.session_state.df_original) else 'Non',
                                        str(len(st.session_state.historique_actions))
                                    ]
                                }
                                resume_df = pd.DataFrame(resume_data)
                                resume_df.to_excel(writer, index=False, sheet_name='Résumé')
                        
                        taille_ko = len(output.getvalue()) / 1024
                        enregistrer_export(nom_complet + ".xlsx", "Excel", len(df_export), len(df_export.columns))
                        
                        st.download_button(
                            label="📥 Télécharger le fichier Excel",
                            data=output.getvalue(),
                            file_name=f"{nom_complet}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                    
                    else:
                        if orientation_json == "records (liste)":
                            json_data = df_export.to_json(orient='records', indent=2, force_ascii=False)
                        elif orientation_json == "index (dictionnaire)":
                            json_data = df_export.to_json(orient='index', indent=2, force_ascii=False)
                        else:
                            json_data = df_export.to_json(orient='table', indent=2, force_ascii=False)
                        
                        taille_ko = len(json_data.encode('utf-8')) / 1024
                        enregistrer_export(nom_complet + ".json", "JSON", len(df_export), len(df_export.columns))
                        
                        st.download_button(
                            label="📥 Télécharger le fichier JSON",
                            data=json_data,
                            file_name=f"{nom_complet}.json",
                            mime="application/json",
                            use_container_width=True
                        )
                    
                    st.success("✅ Export généré avec succès!")
                    st.info("👉 Retournez à l'accueil pour voir le tableau de bord mis à jour")
                    
                except Exception as e:
                    st.error(f"❌ Erreur: {e}")
        
        with col_right:
            st.subheader("Aperçu")
            st.dataframe(df.head(10), use_container_width=True)
            
            st.metric("Lignes", len(df))
            st.metric("Colonnes", len(df.columns))
    
    else:
        st.warning("⚠️ Aucun fichier chargé.")