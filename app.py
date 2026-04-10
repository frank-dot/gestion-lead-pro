from reputation_checker import ReputationChecker
import streamlit as st
import pandas as pd
import re
from datetime import datetime
from collections import Counter
import io
import json
import os
import hashlib
import time
import random
import sqlite3
import chardet
from auth_shared import (
    PERMISSION_LEADS,
    PERMISSION_FINANCE,
    PERMISSION_IMPORT,
    PERMISSION_TELEPHONE,
    PERMISSION_DOUBLONS,
    PERMISSION_FILTRE,
    PERMISSION_EXPORT,
    PERMISSION_VERIF_SDA,
    PERMISSION_ALERTES,
    PERMISSION_BASE_SDA,
    PERMISSION_FIN_DASHBOARD,
    PERMISSION_FIN_MENSUEL,
    PERMISSION_FIN_SUIVI,
    default_permissions,
    has_permission,
    hash_password as shared_hash_password,
    charger_utilisateurs as shared_charger_utilisateurs,
    sauvegarder_utilisateurs as shared_sauvegarder_utilisateurs,
    creer_utilisateur_defaut as shared_creer_utilisateur_defaut,
    authentifier as shared_authentifier,
)

# Initialisation de la base SDA
from sda_database import init_database
init_database()
from sda_operations import SDAManager

# ============================================================================
# CHARGEMENT DE LA CONFIGURATION AU DÉMARRAGE
# ============================================================================
from email_alerter import EmailAlerter
from scheduler import VerificationScheduler
# Initialiser l'alerter une seule fois au démarrage
if 'alerter' not in st.session_state:
    st.session_state.alerter = EmailAlerter()
    st.session_state.config_chargee = st.session_state.alerter.config is not None
# AJOUT CES LIGNES POUR INITIALISER LE SCHEDULER
if 'scheduler' not in st.session_state:
    st.session_state.scheduler = VerificationScheduler()    
# ============================================================================
# GESTION DES NOTIFICATIONS (version simple et fiable)
# ============================================================================
def show_popup(message, type="info", duration=None):
    """
    Affiche une notification dans l'interface Streamlit
    type: "success", "info", "warning", "error"
    duration: ignoré (les messages restent jusqu'à la prochaine interaction)
    """
    if type == "success":
        st.success(f"✅ {message}")
    elif type == "info":
        st.info(f"ℹ️ {message}")
    elif type == "warning":
        st.warning(f"⚠️ {message}")
    elif type == "error":
        st.error(f"❌ {message}")

# ============================================================================
# NOUVEAU: Gestion de l'historique persistant
# ============================================================================
FICHIER_HISTORIQUE = "historique_exports.json"

def charger_historique():
    """Charge l'historique des exports depuis le fichier JSON"""
    if os.path.exists(FICHIER_HISTORIQUE):
        try:
            with open(FICHIER_HISTORIQUE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Reconvertir les timestamps string en datetime
                for export in data:
                    export['timestamp'] = datetime.fromisoformat(export['timestamp'])
                return data
        except Exception as e:
            print(f"Erreur chargement historique: {e}")
            return []
    return []

def sauvegarder_historique():
    """Sauvegarde l'historique des exports dans le fichier JSON"""
    try:
        historique_serializable = []
        for export in st.session_state.historique_exports:
            export_copy = export.copy()
            export_copy['timestamp'] = export['timestamp'].isoformat()
            historique_serializable.append(export_copy)
        
        with open(FICHIER_HISTORIQUE, 'w', encoding='utf-8') as f:
            json.dump(historique_serializable, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erreur sauvegarde historique: {e}")

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
    return shared_hash_password(mot_de_passe)

def charger_utilisateurs():
    """Charge les utilisateurs depuis le fichier JSON"""
    return shared_charger_utilisateurs()

def sauvegarder_utilisateurs(utilisateurs):
    """Sauvegarde les utilisateurs dans le fichier JSON"""
    shared_sauvegarder_utilisateurs(utilisateurs)

def creer_utilisateur_defaut():
    """Crée un utilisateur admin par défaut si aucun n'existe"""
    return shared_creer_utilisateur_defaut()

def authentifier(identifiant, mot_de_passe):
    """Vérifie les identifiants de connexion"""
    return shared_authentifier(identifiant, mot_de_passe)

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
        'permissions': {},
        'df_original': None,
        'df_travail': None,
        'nom_fichier': '',
        'historique_actions': [],
        'position_historique': -1,
        'historique_exports': [],  # Sera chargé depuis le fichier
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
    
    # NOUVEAU: Charger l'historique persistant au démarrage
    if 'historique_exports_charge' not in st.session_state:
        historique_charge = charger_historique()
        if historique_charge:
            st.session_state.historique_exports = historique_charge
            # Recalculer le tableau de bord à partir de l'historique chargé
            st.session_state.tableau_de_bord['total_exports'] = len(st.session_state.historique_exports)
            st.session_state.tableau_de_bord['total_lignes_exportees'] = sum(e['lignes'] for e in st.session_state.historique_exports)
            
            # Compter les formats
            formats = {}
            for e in st.session_state.historique_exports:
                formats[e['format']] = formats.get(e['format'], 0) + 1
            st.session_state.tableau_de_bord['formats_utilises'] = formats
            
            if st.session_state.historique_exports:
                st.session_state.tableau_de_bord['dernier_export'] = st.session_state.historique_exports[-1]
        
        st.session_state.historique_exports_charge = True

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

# NOUVEAU: Version modifiée d'enregistrement d'export avec sauvegarde persistante
def enregistrer_export(nom_fichier, format_export, lignes, colonnes):
    """Enregistre un export dans l'historique et sauvegarde dans le fichier"""
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
    
    # NOUVEAU: Sauvegarder dans le fichier
    sauvegarder_historique()
    
    # NOUVEAU: Afficher un pop-up de confirmation
    show_popup(f"✅ Export enregistré: {lignes} lignes", "success", 3)

def se_connecter(identifiant, user_info):
    """Gère la connexion"""
    st.session_state.authentifie = True
    st.session_state.nom = user_info.get("nom", identifiant)
    st.session_state.identifiant = identifiant
    st.session_state.role = user_info.get("role", "user")
    st.session_state.permissions = user_info.get(
        "permissions",
        default_permissions(st.session_state.role)
    )
    can_leads = has_permission(user_info, PERMISSION_LEADS)
    can_finance = has_permission(user_info, PERMISSION_FINANCE)

    if can_leads and can_finance:
        st.session_state.page = "hub"
    elif can_leads:
        st.session_state.page = "accueil"
    elif can_finance:
        st.session_state.page = "redirect_finance"
    else:
        st.session_state.page = "no_access"
    show_popup(f"👋 Bonjour {st.session_state.nom} !", "success", 2)

def se_deconnecter():
    """Gère la déconnexion"""
    st.session_state.authentifie = False
    st.session_state.page = "login"
    st.session_state.nom = ''
    st.session_state.identifiant = ''
    st.session_state.role = 'user'
    st.session_state.permissions = {}
    st.session_state.df_original = None
    st.session_state.df_travail = None
    st.session_state.nom_fichier = ''
    st.session_state.historique_actions = []
    st.session_state.position_historique = -1
    show_popup("👋 À bientôt !", "info", 2)

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
        show_popup(f"✅ Session chargée: {data.get('date_sauvegarde', '')}", "success", 3)
        return True
    except:
        show_popup("❌ Erreur chargement session", "error", 3)
        return False

def aller_a(page):
    """Navigation entre les pages"""
    st.session_state.page = page
    st.rerun()


def appliquer_visibilite_navigation(can_leads: bool, can_finance: bool):
    """
    Masque les entrées de navigation Streamlit selon les privilèges.
    Hypothèse: 2 pages visibles dans la nav (app, Nogali Finance).
    """
    st.markdown(
        "<style>[data-testid='stSidebarNav']{display:none !important;}</style>",
        unsafe_allow_html=True,
    )


def utilisateur_a_droit(permission_key: str) -> bool:
    user_ctx = {
        "role": st.session_state.get("role", "user"),
        "permissions": st.session_state.get("permissions", {}),
    }
    return has_permission(user_ctx, permission_key)

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
        st.markdown("### Applications")
        if utilisateur_a_droit(PERMISSION_LEADS):
            st.page_link("app.py", label="Gestion Leads et SDA", icon="📋")
        if utilisateur_a_droit(PERMISSION_FINANCE):
            st.page_link("pages/2_Nogali_Finance.py", label="Nogali Finance", icon="💰")
        if st.session_state.get("role") == "super_admin":
            st.page_link("pages/3_Gestion_Utilisateurs.py", label="Gestion Utilisateurs", icon="👥")
        st.markdown("---")

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
                            show_popup("↩️ Action annulée", "info", 2)
                            st.rerun()
                with col2:
                    if st.button("↪️ Refaire", use_container_width=True):
                        df = refaire()
                        if df is not None:
                            st.session_state.df_travail = df
                            show_popup("↪️ Action rétablie", "info", 2)
                            st.rerun()
            
            # NOUVEAU: Section Réinitialisation
            if st.session_state.df_original is not None and st.session_state.df_travail is not None:
                if len(st.session_state.df_travail) != len(st.session_state.df_original):
                    st.markdown("---")
                    st.markdown("**🔄 Réinitialisation**")
                    if st.button("↩️ Revenir au fichier original", use_container_width=True, type="primary"):
                        st.session_state.df_travail = st.session_state.df_original.copy()
                        sauvegarder_etat(st.session_state.df_travail)
                        show_popup("✅ Fichier original restauré", "success", 2)
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
                st.rerun()
        
        st.markdown("---")
        if st.button("🚪 Se déconnecter", use_container_width=True):
            se_deconnecter()
            st.rerun()

def afficher_carte_fonctionnalite(icone, titre, couleur, page, disabled=False):
    """Affiche une carte de fonctionnalité cliquable (sans bouton visible)"""
    
    # Créer une clé unique pour chaque carte
    import hashlib
    import time
    unique_id = hashlib.md5(f"{titre}_{page}_{time.time()}".encode()).hexdigest()[:8]
    btn_key = f"btn_{page}_{unique_id}"
    
    # Style de la carte
    style = f"""
        background: {couleur};
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
        color: white;
        margin-bottom: 0.8rem;
        opacity: {0.5 if disabled else 1};
        font-size: 0.9rem;
        cursor: {'pointer' if not disabled else 'default'};
        transition: all 0.2s ease;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    """
    
    # Si la carte est cliquable, on crée un bouton invisible
    if not disabled and page:
        # Créer un bouton Streamlit avec une clé unique
        bouton_clique = st.button(f"📌 {titre}", key=btn_key, use_container_width=True)
        
        # Masquer le bouton avec du CSS
        st.markdown(f"""
            <style>
                div[data-testid="stButton"]:has(button[key="{btn_key}"]) {{
                    display: none;
                }}
            </style>
        """, unsafe_allow_html=True)
        
        # Si le bouton est cliqué, navigation
        if bouton_clique:
            aller_a(page)
        
        # Carte cliquable qui déclenche le bouton
        st.markdown(f"""
            <div style="{style}" onclick="document.querySelector('button[key=\\'{btn_key}\\']').click();">
                <div style="font-size: 2rem;">{icone}</div>
                <div style="font-size: 1rem; font-weight: bold;">{titre}</div>
            </div>
        """, unsafe_allow_html=True)
    
    else:
        # Version non cliquable (simple affichage)
        st.markdown(f"""
            <div style="{style}">
                <div style="font-size: 2rem;">{icone}</div>
                <div style="font-size: 1rem; font-weight: bold;">{titre}</div>
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

def extraire_code_postal(adresse):
    """Extrait un code postal français (5 chiffres) d'une adresse"""
    if pd.isna(adresse):
        return None
    
    # Convertir en string et nettoyer
    adresse_str = str(adresse)
    
    # Enlever le .0 si présent
    if '.0' in adresse_str:
        adresse_str = adresse_str.replace('.0', '')
    
    # Chercher un groupe de 4 ou 5 chiffres
    match = re.search(r'\b(\d{4,5})\b', adresse_str)
    if match:
        code = match.group(1)
        # Si le code a 4 chiffres, ajouter un zéro devant
        if len(code) == 4:
            return f"0{code}"
        return code
    
    return None
def afficher_gestion_utilisateurs():
    """Affiche l'interface de gestion des utilisateurs"""
    st.subheader("👥 Gestion des utilisateurs")
    
    utilisateurs = charger_utilisateurs()
    
    # Afficher la liste des utilisateurs existants
    st.write("### Utilisateurs existants")
    
    for identifiant, infos in utilisateurs.items():
        permissions = infos.get("permissions", default_permissions(infos.get("role", "user")))
        col1, col2, col3, col4, col5, col6 = st.columns([2, 2, 1, 1, 1, 1])
        with col1:
            st.write(f"**{infos['nom']}**")
        with col2:
            st.write(f"@{identifiant}")
        with col3:
            if infos['role'] == 'super_admin':
                role = "👑 Super Admin"
            elif infos['role'] == 'admin':
                role = "🛡️ Admin"
            else:
                role = "👤 User"
            st.write(role)
        with col4:
            st.write("✅ Leads" if permissions.get("access_admin_leads_pro", False) else "❌ Leads")
        with col5:
            st.write("✅ Finance" if permissions.get("access_nogali_finance", False) else "❌ Finance")
        with col6:
            if identifiant not in ["admin", "superadmin"]:  # Comptes systeme protégés
                if st.button("🗑️", key=f"del_{identifiant}"):
                    del utilisateurs[identifiant]
                    sauvegarder_utilisateurs(utilisateurs)
                    show_popup(f"✅ Utilisateur {identifiant} supprimé", "success", 2)
                    st.rerun()
        st.markdown("---")

    with st.expander("🔐 Modifier les droits d'accès", expanded=False):
        if utilisateurs:
            selected_user = st.selectbox("Utilisateur", list(utilisateurs.keys()), key="perm_user_select")
            user_info = utilisateurs[selected_user]
            current_role = user_info.get("role", "user")
            current_permissions = user_info.get("permissions", default_permissions(current_role))

            st.markdown("**Rôle utilisateur**")
            new_role_value = st.selectbox(
                "Changer le rôle",
                ["user", "admin", "super_admin"],
                index=["user", "admin", "super_admin"].index(current_role) if current_role in ["user", "admin", "super_admin"] else 0,
                key=f"role_select_{selected_user}",
            )
            if st.button("💾 Enregistrer le rôle", key="save_role_btn", use_container_width=True):
                if selected_user == "superadmin" and new_role_value != "super_admin":
                    show_popup("Le compte superadmin doit rester super_admin", "error", 3)
                elif selected_user == "admin" and new_role_value == "user":
                    show_popup("Le compte admin ne peut pas être rétrogradé en user", "error", 3)
                else:
                    utilisateurs[selected_user]["role"] = new_role_value
                    # Harmonise les permissions manquantes selon le nouveau rôle.
                    merged = default_permissions(new_role_value)
                    existing = utilisateurs[selected_user].get("permissions", {})
                    if isinstance(existing, dict):
                        merged.update(existing)
                    utilisateurs[selected_user]["permissions"] = merged
                    sauvegarder_utilisateurs(utilisateurs)
                    show_popup(f"✅ Rôle mis à jour pour @{selected_user}", "success", 2)
                    st.rerun()
            st.markdown("---")

            st.markdown("**Modifier le mot de passe**")
            pwd1 = st.text_input("Nouveau mot de passe", type="password", key=f"pwd1_{selected_user}")
            pwd2 = st.text_input("Confirmer mot de passe", type="password", key=f"pwd2_{selected_user}")
            if st.button("🔑 Mettre à jour le mot de passe", key="save_password_btn", use_container_width=True):
                if not pwd1 or not pwd2:
                    show_popup("Veuillez remplir les deux champs de mot de passe", "warning", 3)
                elif pwd1 != pwd2:
                    show_popup("Les mots de passe ne correspondent pas", "error", 3)
                elif len(pwd1) < 6:
                    show_popup("Le mot de passe doit contenir au moins 6 caractères", "warning", 3)
                else:
                    utilisateurs[selected_user]["mot_de_passe"] = hash_password(pwd1)
                    sauvegarder_utilisateurs(utilisateurs)
                    show_popup(f"✅ Mot de passe mis à jour pour @{selected_user}", "success", 2)
                    st.rerun()
            st.markdown("---")

            can_access_leads = st.checkbox(
                "Accès application Admin Leads Pro",
                value=bool(current_permissions.get("access_admin_leads_pro", current_role in ["admin", "super_admin"])),
                key=f"perm_leads_{selected_user}"
            )
            can_access_finance = st.checkbox(
                "Accès application Nogali Finance",
                value=bool(current_permissions.get("access_nogali_finance", current_role in ["admin", "super_admin"])),
                key=f"perm_finance_{selected_user}"
            )
            st.markdown("**Droits modules internes (Nogali Finance)**")
            f1, f2, f3 = st.columns(3)
            with f1:
                perm_fin_dashboard = st.checkbox(
                    "Finance - Tableau de bord",
                    value=bool(current_permissions.get("access_fin_dashboard", True)),
                    key=f"perm_f_dash_{selected_user}",
                )
            with f2:
                perm_fin_mensuel = st.checkbox(
                    "Finance - Vue mensuelle",
                    value=bool(current_permissions.get("access_fin_mensuel", True)),
                    key=f"perm_f_mens_{selected_user}",
                )
            with f3:
                perm_fin_suivi = st.checkbox(
                    "Finance - Suivi paiements",
                    value=bool(current_permissions.get("access_fin_suivi", True)),
                    key=f"perm_f_suiv_{selected_user}",
                )
            st.markdown("**Droits modules internes (Gestion Leads et SDA)**")
            c1, c2 = st.columns(2)
            with c1:
                perm_import = st.checkbox("Module IMPORT", value=bool(current_permissions.get("access_module_import", False)), key=f"perm_import_{selected_user}")
                perm_telephone = st.checkbox("Module TÉLÉPHONE", value=bool(current_permissions.get("access_module_telephone", False)), key=f"perm_tel_{selected_user}")
                perm_doublons = st.checkbox("Module DOUBLONS", value=bool(current_permissions.get("access_module_doublons", False)), key=f"perm_dbl_{selected_user}")
                perm_filtre = st.checkbox("Module FILTRE", value=bool(current_permissions.get("access_module_filtre", False)), key=f"perm_fil_{selected_user}")
            with c2:
                perm_export = st.checkbox("Module EXPORT", value=bool(current_permissions.get("access_module_export", False)), key=f"perm_exp_{selected_user}")
                perm_verif_sda = st.checkbox("Module VÉRIF SDA", value=bool(current_permissions.get("access_module_verif_sda", False)), key=f"perm_vsda_{selected_user}")
                perm_alertes = st.checkbox("Module ALERTES", value=bool(current_permissions.get("access_module_alertes", False)), key=f"perm_alt_{selected_user}")
                perm_base_sda = st.checkbox("Module BASE SDA", value=bool(current_permissions.get("access_module_base_sda", False)), key=f"perm_bsda_{selected_user}")

            if st.button("💾 Enregistrer les droits", key="save_permissions_btn", use_container_width=True):
                utilisateurs[selected_user]["permissions"] = {
                    "access_admin_leads_pro": can_access_leads,
                    "access_nogali_finance": can_access_finance,
                    "access_fin_dashboard": perm_fin_dashboard,
                    "access_fin_mensuel": perm_fin_mensuel,
                    "access_fin_suivi": perm_fin_suivi,
                    "access_module_import": perm_import,
                    "access_module_telephone": perm_telephone,
                    "access_module_doublons": perm_doublons,
                    "access_module_filtre": perm_filtre,
                    "access_module_export": perm_export,
                    "access_module_verif_sda": perm_verif_sda,
                    "access_module_alertes": perm_alertes,
                    "access_module_base_sda": perm_base_sda,
                }
                sauvegarder_utilisateurs(utilisateurs)
                show_popup(f"✅ Droits mis à jour pour @{selected_user}", "success", 2)
                st.rerun()
    
    # Formulaire d'ajout
    with st.expander("➕ Ajouter un nouvel utilisateur"):
        with st.form("form_ajout_utilisateur"):
            new_id = st.text_input("Identifiant")
            new_nom = st.text_input("Nom complet")
            new_mdp = st.text_input("Mot de passe", type="password")
            new_mdp2 = st.text_input("Confirmer mot de passe", type="password")
            new_role = st.selectbox("Rôle", ["user", "admin", "super_admin"])
            access_leads_new = st.checkbox(
                "Accès Admin Leads Pro",
                value=True
            )
            access_finance_new = st.checkbox(
                "Accès Nogali Finance",
                value=(new_role in ["admin", "super_admin"])
            )
            st.markdown("**Modules Finance activés**")
            fnew1, fnew2, fnew3 = st.columns(3)
            with fnew1:
                access_fin_dashboard_new = st.checkbox("Tableau de bord Finance", value=True)
            with fnew2:
                access_fin_mensuel_new = st.checkbox("Vue mensuelle Finance", value=True)
            with fnew3:
                access_fin_suivi_new = st.checkbox("Suivi paiements Finance", value=True)
            st.markdown("**Modules internes activés**")
            mcol1, mcol2 = st.columns(2)
            with mcol1:
                access_import_new = st.checkbox("IMPORT", value=True)
                access_telephone_new = st.checkbox("TÉLÉPHONE", value=True)
                access_doublons_new = st.checkbox("DOUBLONS", value=True)
                access_filtre_new = st.checkbox("FILTRE", value=True)
            with mcol2:
                access_export_new = st.checkbox("EXPORT", value=True)
                access_verif_sda_new = st.checkbox("VÉRIF SDA", value=(new_role in ["admin", "super_admin"]))
                access_alertes_new = st.checkbox("ALERTES", value=(new_role in ["admin", "super_admin"]))
                access_base_sda_new = st.checkbox("BASE SDA", value=(new_role in ["admin", "super_admin"]))
            
            if st.form_submit_button("Créer l'utilisateur"):
                if not new_id or not new_nom or not new_mdp:
                    show_popup("Tous les champs sont requis", "warning", 3)
                elif new_mdp != new_mdp2:
                    show_popup("Les mots de passe ne correspondent pas", "error", 3)
                elif len(new_mdp) < 4:
                    show_popup("Le mot de passe doit faire au moins 4 caractères", "warning", 3)
                else:
                    utilisateurs = charger_utilisateurs()
                    if new_id in utilisateurs:
                        show_popup("Cet identifiant existe déjà", "error", 3)
                    else:
                        utilisateurs[new_id] = {
                            "nom": new_nom,
                            "mot_de_passe": hash_password(new_mdp),
                            "role": new_role,
                            "permissions": {
                                "access_admin_leads_pro": access_leads_new,
                                "access_nogali_finance": access_finance_new,
                                "access_fin_dashboard": access_fin_dashboard_new,
                                "access_fin_mensuel": access_fin_mensuel_new,
                                "access_fin_suivi": access_fin_suivi_new,
                                "access_module_import": access_import_new,
                                "access_module_telephone": access_telephone_new,
                                "access_module_doublons": access_doublons_new,
                                "access_module_filtre": access_filtre_new,
                                "access_module_export": access_export_new,
                                "access_module_verif_sda": access_verif_sda_new,
                                "access_module_alertes": access_alertes_new,
                                "access_module_base_sda": access_base_sda_new,
                            },
                            "date_creation": datetime.now().isoformat()
                        }
                        sauvegarder_utilisateurs(utilisateurs)
                        show_popup(f"✅ Utilisateur {new_id} créé avec succès", "success", 3)
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

# Force toujours le retour à la page de connexion si la session est fermée.
if not st.session_state.get("authentifie", False) and st.session_state.get("page") != "login":
    st.session_state.page = "login"
    st.rerun()

if st.session_state.get("authentifie"):
    user_ctx = {
        "role": st.session_state.get("role", "user"),
        "permissions": st.session_state.get("permissions", {}),
    }
    can_leads = has_permission(user_ctx, PERMISSION_LEADS)
    can_finance = has_permission(user_ctx, PERMISSION_FINANCE)
    appliquer_visibilite_navigation(can_leads, can_finance)

    if st.session_state.page == "redirect_finance":
        if can_finance:
            st.switch_page("pages/2_Nogali_Finance.py")
        else:
            st.session_state.page = "no_access"
            st.rerun()

    if st.session_state.page not in ["login", "no_access", "hub"] and not can_leads:
        if can_finance:
            st.switch_page("pages/2_Nogali_Finance.py")
        else:
            st.session_state.page = "no_access"
            st.rerun()

    module_permissions = {
        "import": PERMISSION_IMPORT,
        "telephone": PERMISSION_TELEPHONE,
        "doublons": PERMISSION_DOUBLONS,
        "filtre": PERMISSION_FILTRE,
        "export": PERMISSION_EXPORT,
        "verification_sda": PERMISSION_VERIF_SDA,
        "config_alertes": PERMISSION_ALERTES,
        "gestion_sda": PERMISSION_BASE_SDA,
    }
    current_page = st.session_state.get("page")
    required_permission = module_permissions.get(current_page)
    if required_permission and not utilisateur_a_droit(required_permission):
        show_popup("⛔ Accès refusé à ce module", "error", 3)
        st.session_state.page = "accueil"
        st.rerun()

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
        [data-testid="stSidebar"],
        [data-testid="stSidebarNav"],
        [data-testid="collapsedControl"] {
            display: none !important;
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
                        <h1>🔐 Nogali Solutions Services Pro</h1>
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
                            show_popup("❌ Identifiant ou mot de passe incorrect", "error", 3)
                    else:
                        show_popup("⚠️ Veuillez remplir tous les champs", "warning", 3)
            
            # Informations de démo
            st.markdown("""
                
                <div class="footer-text">
                    © 2026 AETECH SOLUTIONS SARL. Tous droits réservés.
                </div>
            """, unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# HUB APPLICATIF (CHOIX PAR PRIVILEGES)
# ----------------------------------------------------------------------------
elif st.session_state.page == "hub":
    afficher_barre_laterale()
    is_super_admin = st.session_state.get("role") == "super_admin"
    hub_class = "super-admin-hub" if is_super_admin else ""
    st.markdown(
        """
        <style>
        .app-cadran {
            border-radius: 18px;
            padding: 1.2rem;
            border: 1px solid color-mix(in srgb, var(--text-color, #111) 22%, transparent 78%);
            background: color-mix(in srgb, var(--secondary-background-color, #f5f6fa) 90%, #5c7cfa 10%);
            box-shadow: 0 8px 24px color-mix(in srgb, var(--text-color, #111) 14%, transparent 86%);
            text-align: center;
            min-height: 170px;
            color: var(--text-color, #111);
        }
        .super-admin-hub .app-cadran {
            border: 1px solid color-mix(in srgb, var(--text-color, #111) 35%, #f1c40f 65%);
            background: linear-gradient(
                145deg,
                color-mix(in srgb, var(--secondary-background-color, #f6f7fb) 86%, #f1c40f 14%),
                color-mix(in srgb, var(--secondary-background-color, #f6f7fb) 82%, #7b61ff 18%)
            );
            box-shadow: 0 10px 28px color-mix(in srgb, var(--text-color, #111) 16%, transparent 84%);
            color: var(--text-color, #111);
        }
        .app-cadran .icon {
            font-size: 2.2rem;
            margin-bottom: 0.35rem;
        }
        .app-cadran .title {
            font-size: 1.15rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }
        .app-cadran .desc {
            opacity: 0.85;
            font-size: 0.92rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"## 🚀 Choix de l'application, {st.session_state.nom}")
    if is_super_admin:
        st.info("👑 Mode Super Admin actif")
    st.caption("L'accès est piloté par vos privilèges.")

    st.markdown(f"<div class='{hub_class}'>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            """
            <div class="app-cadran">
                <div class="icon">📋</div>
                <div class="title">Admin Leads Pro</div>
                <div class="desc">Gestion, traitement et export des contacts.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Ouvrir Admin Leads Pro", use_container_width=True, key="hub_open_leads"):
            st.session_state.page = "accueil"
            st.rerun()
    with col2:
        st.markdown(
            """
            <div class="app-cadran">
                <div class="icon">💰</div>
                <div class="title">Nogali Finance</div>
                <div class="desc">Suivi financier, paiements et trésorerie.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Ouvrir Nogali Finance", use_container_width=True, key="hub_open_finance"):
            st.switch_page("pages/2_Nogali_Finance.py")
    st.markdown("</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# PAGE SANS ACCES
# ----------------------------------------------------------------------------
elif st.session_state.page == "no_access":
    st.error("⛔ Votre compte n'a accès à aucune application.")
    if st.button("Se déconnecter", use_container_width=True):
        se_deconnecter()
        st.rerun()

# ----------------------------------------------------------------------------
# PAGE D'ACCUEIL (VERSION AVEC BOUTONS COLORÉS)
# ----------------------------------------------------------------------------
elif st.session_state.page == "accueil":
    afficher_barre_laterale()
    
    st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 1.5rem; border-radius: 10px; color: white; margin: 1rem 0;
                    text-align: center; font-size: 1.8rem; font-weight: bold;">
            📋 Bienvenue {st.session_state.nom} !
        </div>
    """, unsafe_allow_html=True)
    
    afficher_tableau_de_bord()
    
    # Gestion des utilisateurs déplacée vers la page dédiée `Gestion Utilisateurs`.
    
    st.markdown("---")
    st.markdown("## 🚀 Modules disponibles")
    
    # CSS personnalisé pour les boutons
    st.markdown("""
        <style>
        /* Style de base pour tous les boutons */
        div.stButton > button {
            border-radius: 8px;
            padding: 0.5rem 1rem;
            font-weight: bold;
            transition: all 0.3s ease;
            border: none;
            color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            background: linear-gradient(145deg, #4158D0, #C850C0);
        }
        
        /* Effet au survol pour tous les boutons */
        div.stButton > button:hover {
            filter: brightness(1.2);
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }
        
        /* Couleurs par module - basé sur le texte du bouton */
        div.stButton > button:has(span:contains("IMPORT")) {
            background: linear-gradient(135deg, #3498db, #2980b9) !important;
        }
        
        div.stButton > button:has(span:contains("TÉLÉPHONE")) {
            background: linear-gradient(135deg, #2ecc71, #27ae60) !important;
        }
        
        div.stButton > button:has(span:contains("DOUBLONS")) {
            background: linear-gradient(135deg, #e74c3c, #c0392b) !important;
        }
        
        div.stButton > button:has(span:contains("FILTRE")) {
            background: linear-gradient(135deg, #f39c12, #e67e22) !important;
        }
        
        div.stButton > button:has(span:contains("VÉRIF SDA")) {
            background: linear-gradient(135deg, #9b59b6, #8e44ad) !important;
        }
        
        div.stButton > button:has(span:contains("ALERTES")) {
            background: linear-gradient(135deg, #e74c3c, #c0392b) !important;
        }
        
        div.stButton > button:has(span:contains("BASE SDA")) {
            background: linear-gradient(135deg, #27ae60, #229954) !important;
        }
        
        div.stButton > button:has(span:contains("À VENIR")) {
            background: linear-gradient(135deg, #95a5a6, #7f8c8d) !important;
            opacity: 0.7;
        }
        
        div.stButton > button:has(span:contains("EXPORTER")) {
            background: linear-gradient(135deg, #667eea, #764ba2) !important;
            font-size: 1.2rem;
            padding: 0.8rem;
        }
        </style>
    """, unsafe_allow_html=True)
    
    
    # ===== SECTION 1 : GESTION DES LEADS =====
    st.markdown("### 📊 GESTION DES LEADS")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        disabled = not utilisateur_a_droit(PERMISSION_IMPORT)
        if st.button("📂 IMPORT", key="btn_import", disabled=disabled, use_container_width=True):
            st.session_state.page = "import"
            st.rerun()
    
    with col2:
        disabled = st.session_state.df_original is None or not utilisateur_a_droit(PERMISSION_TELEPHONE)
        if st.button("📞 TÉLÉPHONE", key="btn_telephone", disabled=disabled, use_container_width=True):
            st.session_state.page = "telephone"
            st.rerun()
    
    with col3:
        disabled = st.session_state.df_original is None or not utilisateur_a_droit(PERMISSION_DOUBLONS)
        if st.button("🗑️ DOUBLONS", key="btn_doublons", disabled=disabled, use_container_width=True):
            st.session_state.page = "doublons"
            st.rerun()
    
    with col4:
        disabled = st.session_state.df_original is None or not utilisateur_a_droit(PERMISSION_FILTRE)
        if st.button("🔍 FILTRE", key="btn_filtre", disabled=disabled, use_container_width=True):
            st.session_state.page = "filtre"
            st.rerun()
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ===== SECTION 2 : GESTION ET SUIVI DES SDA =====
    st.markdown("🛡️ GESTION ET SUIVI DES SDA")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        disabled = st.session_state.df_original is None or not utilisateur_a_droit(PERMISSION_VERIF_SDA)
        if st.button("🔎 VÉRIF SDA", key="btn_verif_sda", disabled=disabled, use_container_width=True):
            st.session_state.page = "verification_sda"
            st.rerun()
    if st.session_state.role in ["admin", "super_admin"]:
        with col2:
            disabled = not utilisateur_a_droit(PERMISSION_ALERTES)
            if st.button("📧 ALERTES", key="btn_alertes", disabled=disabled, use_container_width=True):
                st.session_state.page = "config_alertes"
                st.rerun()
        
        with col3:
            disabled = not utilisateur_a_droit(PERMISSION_BASE_SDA)
            if st.button("🗄️ BASE SDA", key="btn_base_sda", disabled=disabled, use_container_width=True):
                st.session_state.page = "gestion_sda"
                st.rerun()
        
        with col4:
            st.button("🔜 À VENIR", key="btn_a_venir", disabled=True, use_container_width=True)
    else:
        # Pour les non-admin, on affiche des cartes vides ou masquées
        with col2:
            st.empty()
        with col3:
            st.empty()
        with col4:
            st.empty()    
    st.markdown("<br>",unsafe_allow_html=True)
    
    # Bouton export
    col1, col2, col3 = st.columns(3)
    with col2:
        disabled = st.session_state.df_original is None or not utilisateur_a_droit(PERMISSION_EXPORT)
        if st.button("💾 EXPORTER", key="btn_export", disabled=disabled, use_container_width=True, type="primary"):
            st.session_state.page = "export"
            st.rerun()

# ----------------------------------------------------------------------------
# PAGE IMPORT (avec mode simple et mode fusion)
# ----------------------------------------------------------------------------
elif st.session_state.page == "import":
    st.title("📂 Import et Fusion de fichiers")
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            aller_a("accueil")
    
    st.markdown("---")
    
    # Choix du mode d'import
    mode_import = st.radio(
        "Mode d'import",
        ["📄 Fichier unique", "🔗 Fusionner plusieurs fichiers"],
        horizontal=True
    )
    
    # ===== MODE FICHIER UNIQUE =====
    if mode_import == "📄 Fichier unique":
        uploaded_file = st.file_uploader(
            "Choisir un fichier CSV ou Excel",
            type=['csv', 'xlsx', 'xls'],
            key="file_uploader_single"
        )
        
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    # ===== NOUVEAU CODE AVEC CHARDET =====
                    # Détection de l'encodage
                    bytes_data = uploaded_file.getvalue()
                    result = chardet.detect(bytes_data[:20000])
                    encoding = result['encoding']
                    
                    # Détection du séparateur
                    sample = bytes_data[:1000].decode(encoding, errors='ignore')
                    sep = ';' if sample.count(';') > sample.count(',') else ','
                    
                    # Remise à zéro du pointeur
                    uploaded_file.seek(0)
                    
                    # Analyse de la structure (1 colonne ou plusieurs)
                    sample_df = pd.read_csv(uploaded_file, encoding=encoding, sep=sep, nrows=2, header=None)
                    nb_colonnes = len(sample_df.columns)
                    uploaded_file.seek(0)
                    
                    # CAS 1 : Une seule colonne (liste de numéros)
                    if nb_colonnes == 1:
                        st.info("📁 Format détecté : liste de numéros")
                        try:
                            df = pd.read_csv(uploaded_file, encoding=encoding, sep=sep, header=None, names=['numero'])
                            st.success(f"✅ {len(df)} numéros chargés (Encodage: {encoding}, Séparateur: {sep})")
                        except Exception as e:
                            st.error(f"❌ Erreur de lecture: {e}")
                            st.stop()
                    
                    # CAS 2 : Plusieurs colonnes (tableau normal)
                    else:
                        st.info(f"📁 Format détecté : tableau ({nb_colonnes} colonnes)")
                        try:
                            df = pd.read_csv(uploaded_file, encoding=encoding, sep=sep)
                            st.success(f"✅ Fichier chargé (Encodage: {encoding}, Séparateur: {sep})")
                        except Exception as e:
                            st.error(f"❌ Erreur de lecture: {e}")
                            st.stop()
                
                else:  # Fichier Excel
                    sample = pd.read_excel(uploaded_file, nrows=2, header=None)
                    nb_colonnes = len(sample.columns)
                    
                    if nb_colonnes == 1:
                        st.info("📁 Format détecté : liste de numéros")
                        df = pd.read_excel(uploaded_file, header=None, names=['numero'])
                    else:
                        st.info(f"📁 Format détecté : tableau ({nb_colonnes} colonnes)")
                        df = pd.read_excel(uploaded_file)
                
                # Vérifier les colonnes en double
                a_doublons, doublons = verifier_colonnes_en_double(df)
                if a_doublons:
                    st.warning(f"⚠️ Colonnes en double: {', '.join(doublons)}")
                    if st.button("🔄 Renommer"):
                        df = renommer_colonnes_doublons(df)
                        show_popup("✅ Colonnes renommées", "success")
                
                # Sauvegarder
                st.session_state.df_original = df.copy()
                st.session_state.df_travail = df.copy()
                st.session_state.nom_fichier = uploaded_file.name
                sauvegarder_etat(df)
                
                st.dataframe(df.head(10), use_container_width=True)
                
                if st.button("✅ VALIDER", use_container_width=True, type="primary"):
                    aller_a("accueil")
                    
            except Exception as e:
                st.error(f"❌ Erreur: {e}")
    
    # ===== MODE FUSION MULTI-FICHIERS =====
    else:
        st.subheader("🔗 Fusionner plusieurs fichiers")
        st.markdown("""
        **Comment ça marche :**
        - Importez plusieurs fichiers CSV ou Excel
        - Tous les fichiers seront fusionnés en un seul
        - Les fichiers avec 1 colonne deviennent des listes de numéros
        - Les fichiers avec plusieurs colonnes gardent leurs en-têtes
        """)
        
        uploaded_files = st.file_uploader(
            "Choisir les fichiers à fusionner",
            type=['csv', 'xlsx', 'xls'],
            accept_multiple_files=True,
            key="file_uploader_multi"
        )
        
        if uploaded_files and len(uploaded_files) > 0:
            st.info(f"📦 {len(uploaded_files)} fichier(s) sélectionné(s)")
            
            # Options de fusion
            with st.expander("⚙️ Options de fusion"):
                gestion_doublons = st.radio(
                    "Gestion des doublons",
                    ["Garder tous", "Supprimer les doublons exacts"],
                    key="dedup_option"
                )
                
                type_fusion = st.radio(
                    "Type de fusion",
                    ["Verticale (empiler les lignes)", "Horizontale (joindre les colonnes)"],
                    horizontal=True,
                    key="merge_type"
                )
            
            # Aperçu des fichiers
            with st.expander("📋 Aperçu des fichiers"):
                for i, file in enumerate(uploaded_files):
                    st.markdown(f"**Fichier {i+1}: {file.name}**")
                    try:
                        if file.name.endswith('.csv'):
                            preview_df = pd.read_csv(file, nrows=3)
                        else:
                            preview_df = pd.read_excel(file, nrows=3)
                        st.dataframe(preview_df)
                        st.caption(f"Colonnes: {', '.join(preview_df.columns)}")
                    except:
                        # Si erreur, essayer sans en-tête
                        file.seek(0)
                        if file.name.endswith('.csv'):
                            preview_df = pd.read_csv(file, nrows=3, header=None)
                        else:
                            preview_df = pd.read_excel(file, nrows=3, header=None)
                        st.dataframe(preview_df)
                        st.caption("Format: liste de numéros")
                    finally:
                        file.seek(0)
            
            # Bouton de fusion
            if st.button("🚀 FUSIONNER LES FICHIERS", type="primary", use_container_width=True):
                with st.spinner("Fusion en cours..."):
                    all_dfs = []
                    fusion_success = True
                    progress_bar = st.progress(0)
                    
                    for i, file in enumerate(uploaded_files):
                        try:
                            # Lire chaque fichier intelligemment
                            if file.name.endswith('.csv'):
                                # Tester d'abord avec en-tête
                                file.seek(0)
                                try:
                                    df_test = pd.read_csv(file, nrows=2)
                                    if len(df_test.columns) > 1:
                                        # Plusieurs colonnes → garder en-tête
                                        file.seek(0)
                                        df = pd.read_csv(file)
                                    else:
                                        # Une colonne → lire sans en-tête
                                        file.seek(0)
                                        df = pd.read_csv(file, header=None, names=[f'fichier_{i+1}'])
                                except:
                                    # Si erreur, lire sans en-tête
                                    file.seek(0)
                                    df = pd.read_csv(file, header=None, names=[f'fichier_{i+1}'])
                            
                            else:  # Excel
                                file.seek(0)
                                try:
                                    df_test = pd.read_excel(file, nrows=2)
                                    if len(df_test.columns) > 1:
                                        file.seek(0)
                                        df = pd.read_excel(file)
                                    else:
                                        file.seek(0)
                                        df = pd.read_excel(file, header=None, names=[f'fichier_{i+1}'])
                                except:
                                    file.seek(0)
                                    df = pd.read_excel(file, header=None, names=[f'fichier_{i+1}'])
                            
                            all_dfs.append(df)
                            progress_bar.progress((i + 1) / len(uploaded_files))
                            
                        except Exception as e:
                            st.error(f"❌ Erreur sur {file.name}: {e}")
                            fusion_success = False
                            break
                    
                    if fusion_success and all_dfs:
                        # Fusion selon le type choisi
                        if type_fusion == "Verticale (empiler les lignes)":
                            df_fusion = pd.concat(all_dfs, ignore_index=True, sort=False)
                        else:
                            # Fusion horizontale (sur l'index)
                            df_fusion = pd.concat(all_dfs, axis=1, ignore_index=False)
                        # 👇 NOUVEAU : Tout rassembler dans une seule colonne 'numero'
                        st.info("🔄 Reformatage des données en une seule colonne...")
                        
                        # Créer une liste vide pour tous les numéros
                        tous_les_numeros = []
                        
                        # Parcourir toutes les colonnes du DataFrame fusionné
                        for col in df_fusion.columns:
                            # Ajouter les valeurs non vides de chaque colonne
                            valeurs = df_fusion[col].dropna().astype(str).tolist()
                            # Nettoyer chaque valeur
                            valeurs = [str(int(float(v))) if '.0' in v else v for v in valeurs]
                            tous_les_numeros.extend(valeurs)
                        
                        # Créer un nouveau DataFrame avec une seule colonne
                        df_final = pd.DataFrame({'numero': tous_les_numeros})
                        
                        # Supprimer les doublons éventuels
                        avant = len(df_final)
                        df_final = df_final.drop_duplicates()
                        apres = len(df_final)
                        
                        if avant > apres:
                            st.info(f"🗑️ {avant - apres} doublons supprimés")
                        
                        st.success(f"✅ {len(df_final)} numéros uniques prêts pour la vérification")
                        
                        # Remplacer df_fusion par df_final
                        df_fusion = df_final
                        # Gestion des doublons
                        avant = len(df_fusion)
                        if gestion_doublons == "Supprimer les doublons exacts":
                            df_fusion = df_fusion.drop_duplicates()
                            apres = len(df_fusion)
                            st.success(f"✅ {avant - apres} doublons supprimés")
                        
                        # Sauvegarder le résultat
                        st.session_state.df_original = df_fusion.copy()
                        st.session_state.df_travail = df_fusion.copy()
                        st.session_state.nom_fichier = f"fusion_{len(uploaded_files)}_fichiers"
                        sauvegarder_etat(df_fusion)
                        
                        st.success(f"✅ Fusion réussie! {len(df_fusion)} lignes, {len(df_fusion.columns)} colonnes")
                        st.dataframe(df_fusion.head(10), use_container_width=True)
                        
                        if st.button("✅ UTILISER CE FICHIER", use_container_width=True, type="primary"):
                            aller_a("accueil")
    
    st.markdown("---")
    if st.button("🏠 Retour à l'accueil", use_container_width=True):
        aller_a("accueil")

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
        
        with col_left:  # ← Maintenant bien indenté sous le if
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
                show_popup("✅ Téléphones formatés avec succès", "success")
                # Le rerun n'est pas nécessaire, le dataframe est déjà modifié
        
        with col_right:  # ← Maintenant bien indenté sous le if
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
                    show_popup(f"✅ {avant - apres} doublons supprimés! {apres} lignes restantes", "success", 3)
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
                    show_popup(f"✅ {avant - apres} doublons supprimés! {apres} lignes restantes", "success", 3)
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


                    # ===== GESTION DES FILTRES CUMULATIFS (PANIER) =====
            st.markdown("---")
            st.subheader("🛒 Panier de filtres")

            # Initialiser le panier
            if 'panier_filtres' not in st.session_state:
                st.session_state.panier_filtres = []

            # Afficher les filtres déjà dans le panier
            if st.session_state.panier_filtres:
                st.markdown("### 📋 Filtres en attente")
                
                for i, filtre in enumerate(st.session_state.panier_filtres):
                    with st.container():
                        col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                        
                        with col1:
                            st.info(f"**{filtre['colonne']}**")
                        
                        with col2:
                            st.write(f"{filtre['mode']} : {filtre['critere']}")
                        
                        with col3:
                            if st.button(f"✏️", key=f"edit_{i}"):
                                # Remplir les champs avec ce filtre (à implémenter)
                                st.session_state.filtre_en_edition = filtre
                                st.rerun()
                        
                        with col4:
                            if st.button(f"❌", key=f"remove_{i}"):
                                st.session_state.panier_filtres.pop(i)
                                st.rerun()
                
                # Mode de combinaison
                mode_combinaison = st.radio(
                    "Combinaison des filtres",
                    ["🔵 ET (tous les critères)", "🟠 OU (au moins un critère)"],
                    horizontal=True
                )
                
                # Bouton pour appliquer tous les filtres
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ APPLIQUER TOUS LES FILTRES", type="primary", use_container_width=True):
                        with st.spinner("Application des filtres..."):
                            df_temp = st.session_state.df_original.copy()
                            
                            if mode_combinaison == "🔵 ET (tous les critères)":
                                # AND : tous les filtres doivent être vrais
                                for filtre in st.session_state.panier_filtres:
                                    masque = df_temp[filtre['colonne']].apply(filtre['fonction'])
                                    df_temp = df_temp[masque]
                            else:
                                # OR : au moins un filtre doit être vrai
                                masque_global = pd.Series([False] * len(df_temp), index=df_temp.index)
                                for filtre in st.session_state.panier_filtres:
                                    masque = df_temp[filtre['colonne']].apply(filtre['fonction'])
                                    masque_global = masque_global | masque
                                df_temp = df_temp[masque_global]
                            
                            st.session_state.df_travail = df_temp.copy()
                            sauvegarder_etat(st.session_state.df_travail)
                            show_popup(f"✅ {len(df_temp)} résultats", "success")
                            st.session_state.panier_filtres = []  # Vider le panier après application
                            st.rerun()
                
                with col2:
                    if st.button("🔄 VIDER LE PANIER", use_container_width=True):
                        st.session_state.panier_filtres = []
                        st.rerun()

            else:
                st.info("📭 Panier vide. Créez des filtres et ajoutez-les ci-dessous.")

            # ===== AJOUTER LE FILTRE COURANT AU PANIER =====
        st.markdown("---")
        st.subheader("➕ Ajouter le filtre courant")

        # Vérifier si un filtre est défini
        if 'filtre_func' in locals() and filtre_func is not None:
            
            # Calculer le nombre de résultats pour ce filtre
            try:
                masque_test = df[col_filtre].apply(filtre_func)
                nb_resultats_filtre = masque_test.sum()
            except:
                nb_resultats_filtre = 0
            
            # Aperçu du filtre
            st.markdown(f"""
            **Filtre actuel :**  
            - Colonne : `{col_filtre}`  
            - Mode : `{mode_filtre}`  
            - Critères : {criteres_list if 'criteres_list' in locals() else 'N/A'}  
            - Résultats : {nb_resultats_filtre} lignes ({nb_resultats_filtre/len(df)*100:.1f}% du total)
            """)
            
            # Définir la fonction de filtrage pour le panier
            def fonction_panier(x):
                try:
                    return filtre_func(x)
                except:
                    return False
            
            if st.button("➕ AJOUTER AU PANIER", use_container_width=True, type="secondary"):
                st.session_state.panier_filtres.append({
                    'colonne': col_filtre,
                    'mode': mode_filtre,
                    'critere': criteres_list if 'criteres_list' in locals() else 'N/A',
                    'fonction': fonction_panier,
                    'nb_resultats': nb_resultats_filtre
                })
                show_popup(f"✅ Filtre ajouté au panier ({nb_resultats_filtre} lignes)", "success")
                st.rerun()
        else:
            st.info("👆 Configurez d'abord un filtre dans la section ci-dessus")

            

        # ===== NOUVEAU : EXTRACTION DE CODES POSTAUX =====
            st.markdown("---")
            st.subheader("📍 Extraction de codes postaux")

            if st.session_state.df_travail is not None:
                df = st.session_state.df_travail
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Choisir la colonne source
                    colonnes_adresse = [col for col in df.columns if any(
                        x in col.lower() for x in ['adresse', 'address', 'ville', 'lieu', 'rue']
                    )]
                    if not colonnes_adresse:
                        colonnes_adresse = df.columns.tolist()
                    
                    col_source = st.selectbox(
                        "Colonne contenant les adresses",
                        colonnes_adresse,
                        key="col_source_cp"
                    )
                
                with col2:
                    # Nom de la nouvelle colonne
                    nouveau_nom = st.text_input(
                        "Nom de la nouvelle colonne",
                        value="code_postal",
                        key="nom_col_cp"
                    )
                
                if st.button("🔍 EXTRAIRE LES CODES POSTAUX", type="secondary"):
                    with st.spinner("Extraction en cours..."):
                        # 👇 CONVERTIR LA COLONNE SOURCE EN TEXTE AVANT TOUT
                        colonne_source_texte = df[col_source].astype(str)
                        
                        # Extraire les codes
                        codes = colonne_source_texte.apply(extraire_code_postal)
                        
                        # Stocker dans une colonne texte
                        st.session_state.df_travail[nouveau_nom] = codes.astype(str)
                        
                        # Compter les résultats
                        nb_extraits = st.session_state.df_travail[nouveau_nom].str.match(r'^\d{5}$').sum()
                        
                        show_popup(f"✅ {nb_extraits} codes postaux extraits", "success")
                        
                        # Aperçu
                        apercu = df[[col_source, nouveau_nom]].head(10)
                        st.dataframe(apercu, use_container_width=True)
                        
                        # Bouton pour valider l'extraction
                        if st.button("✅ VALIDER CETTE EXTRACTION"):
                            sauvegarder_etat(st.session_state.df_travail)
                            show_popup("✅ Extraction validée et sauvegardée", "success")
                            st.rerun()
            # ===== FIN DE LA NOUVELLE SECTION =====        
            
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
                        
                        #if st.button("✅ CRÉER UN NOUVEAU FICHIER", use_container_width=True, type="primary"):
                         #   df_filtre = df[masque_filtre].copy()
                         #  st.session_state.df_travail = df_filtre
                         #   sauvegarder_etat(st.session_state.df_travail)
                         #   show_popup(f"✅ Nouveau fichier créé avec {nb_resultats} contacts!", "success", 3)
                         #   st.rerun()
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
            
            # NOUVEAU: Bouton pour réinitialiser depuis l'original
            st.markdown("---")
            st.subheader("🔄 Options avancées")
            if st.button("🔄 Partir du fichier original", use_container_width=True):
                st.session_state.df_travail = st.session_state.df_original.copy()
                show_popup("✅ Retour au fichier original", "info", 2)
                st.rerun()
            
            # ======= SECTION FILTRE ET BOUTONS =======
            st.markdown("---")

            # Initialiser les variables
            nb_resultats = 0
            masque_filtre = None

            # Calculer le filtre si possible
            if 'filtre_func' in locals() and filtre_func is not None:
                try:
                    masque_filtre = df[col_filtre].apply(filtre_func)
                    nb_resultats = masque_filtre.sum()
                    
                    # AFFICHAGE UNIQUE des métriques
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Contacts trouvés", nb_resultats)
                    with col2:
                        st.metric("Pourcentage", f"{nb_resultats/len(df)*100:.1f}%")
                    with col3:
                        st.metric("Total lignes", len(df))
                    
                    # Aperçu (optionnel)
                    if nb_resultats > 0:
                        if st.checkbox("👀 Voir l'aperçu des résultats", key="apercu_resultats"):
                            aperçu = df[masque_filtre].head(10)
                            st.dataframe(aperçu, use_container_width=True)
                        
                except Exception as e:
                    st.error(f"Erreur: {e}")

            # Initialiser le flag de session
            if 'fichier_filtre_cree' not in st.session_state:
                st.session_state.fichier_filtre_cree = False
        
            # ========= BOUTON UNIQUE =========
            st.markdown("---")

            # Un SEUL bouton pour créer ET indiquer la création
            if st.button("✅ CRÉER UN NOUVEAU FICHIER", 
                        use_container_width=True, 
                        type="primary",
                        key="btn_creer_fichier_unique"):
                
                # Vérifier que masque_filtre existe
                if 'masque_filtre' in locals() and masque_filtre is not None:
                    df_filtre = df[masque_filtre].copy()
                    st.session_state.df_travail = df_filtre
                    sauvegarder_etat(st.session_state.df_travail)
                    show_popup("✅ Fichier créé avec succès !", "success")
                    st.session_state.fichier_cree = True
                    st.rerun()
                else:
                    st.warning("⚠️ Aucun filtre appliqué")

            # Message de confirmation (pas un deuxième bouton)
            if st.session_state.get('fichier_cree', False):
                st.success("✅ Fichier prêt ! Rendez-vous dans le module Export")
                if st.button("📤 Aller à l'export",  use_container_width=True, 
                     type="primary",
                     key="btn_export_final"):
                    
                    st.session_state.fichier_cree = False
                    aller_a("export")

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
                        
                        # Enregistrer dans l'historique (version modifiée)
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
                        
                        enregistrer_export(nom_complet + ".json", "JSON", len(df_export), len(df_export.columns))
                        
                        st.download_button(
                            label="📥 Télécharger le fichier JSON",
                            data=json_data,
                            file_name=f"{nom_complet}.json",
                            mime="application/json",
                            use_container_width=True
                        )
                    
                    st.success("✅ Export généré avec succès!")
                    
                except Exception as e:
                    st.error(f"❌ Erreur: {e}")
        
        with col_right:
            st.subheader("Aperçu")
            st.dataframe(df.head(10), use_container_width=True)
            
            st.metric("Lignes", len(df))
            st.metric("Colonnes", len(df.columns))
    
    else:
        st.warning("⚠️ Aucun fichier chargé.")

# ----------------------------------------------------------------------------
# PAGE VÉRIFICATION SDA (VERSION SIMPLIFIÉE)
# ----------------------------------------------------------------------------
elif st.session_state.page == "verification_sda":
    st.title("🛡️ Vérification SDA")
    st.markdown("Analyse sur 2 sources : **Google Libphonenumber** + **Numeroinconnu.fr**")
    
    # Bouton retour
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            st.session_state.page = "accueil"
            st.rerun()
    
    st.markdown("---")
    
    # Initialiser le checker
    if 'reputation_checker' not in st.session_state:
        st.session_state.reputation_checker = ReputationChecker()
    
    # Choix de la source
    source = st.radio(
        "Source des numéros",
        ["📁 Fichier actuel", "📝 Coller une liste"],
        horizontal=True
    )
    
    numbers_to_check = []
    
    if source == "📁 Fichier actuel":
        if st.session_state.df_travail is not None:
            col_tel = st.selectbox(
                "Choisir la colonne des numéros",
                st.session_state.df_travail.columns
            )
            
            if st.button("📂 Charger depuis le fichier"):
                raw = st.session_state.df_travail[col_tel].dropna().astype(str)
                cleaned = []
                for n in raw:
                    n_clean = re.sub(r'[\s\-\(\)]', '', str(n))
                    if n_clean:
                        cleaned.append(n_clean)
                
                numbers_to_check = list(dict.fromkeys(cleaned))
                st.session_state.numbers_to_check = numbers_to_check
                st.success(f"✅ {len(numbers_to_check)} numéros chargés")
        else:
            st.warning("⚠️ Veuillez d'abord charger un fichier")
    
    else:
        text_input = st.text_area(
            "Collez vos numéros (un par ligne):",
            height=150,
            placeholder="0612345678\n+33612345678\n0145367890"
        )
        
        if st.button("📋 Charger la liste"):
            numbers = []
            for line in text_input.split('\n'):
                n = line.strip()
                if n:
                    n_clean = re.sub(r'[\s\-\(\)]', '', n)
                    if n_clean:
                        numbers.append(n_clean)
            
            st.session_state.numbers_to_check = numbers
            st.success(f"✅ {len(numbers)} numéros chargés")
    
    # Lancement de la vérification
    if 'numbers_to_check' in st.session_state and st.session_state.numbers_to_check:
        st.markdown("---")
        st.subheader("⚙️ Lancer la vérification")
        
        delay = st.slider("⏱️ Délai entre vérifications (sec)", 1.0, 3.0, 1.5)
        nb_total = len(st.session_state.numbers_to_check)
        st.info(f"📊 {nb_total} numéros à vérifier")
        
        if st.button("🚀 LANCER LA VÉRIFICATION", type="primary", use_container_width=True):
            
            with st.spinner("Vérification en cours..."):
                checker = st.session_state.reputation_checker
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                results = []
                
                for i, num in enumerate(st.session_state.numbers_to_check):
                    status_text.text(f"Analyse {i+1}/{nb_total} : {num}")
                    result = checker.analyze_number(num)
                    results.append(result)
                    progress_bar.progress((i + 1) / nb_total)
                    
                    if i < nb_total - 1:
                        time.sleep(delay)
                
                # Sauvegarde des résultats
                st.session_state.verification_results = pd.DataFrame(results)
                status_text.text("✅ Vérification terminée !")
                show_popup(f"✅ {nb_total} numéros vérifiés", "success")
    
   # Affichage des résultats
    if 'verification_results' in st.session_state:
        df_results = st.session_state.verification_results
        
        st.markdown("---")
        st.subheader("📊 Résultats")
        
        # Créer la colonne danger si elle n'existe pas
        def get_danger_level(row):
            ni = row.get('numeroinconnu', {})
            if isinstance(ni, dict):
                pct = ni.get('danger_percentage', 0)
                if pct >= 70:
                    return "🔴 Dangereux"
                elif pct >= 50:  # Changé à 50% pour correspondre à ta demande
                    return "🟠 Gênant"
                elif pct > 0:
                    return "🟢 Peu risqué"
            return "⚪ Inconnu"
        
        df_results['danger'] = df_results.apply(get_danger_level, axis=1)
        
        # Ajouter une colonne avec le pourcentage
        def get_danger_pct(row):
            ni = row.get('numeroinconnu', {})
            if isinstance(ni, dict):
                return ni.get('danger_percentage', 0)
            return 0
        
        df_results['danger_pct'] = df_results.apply(get_danger_pct, axis=1)
        
        # Métriques mises à jour
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total", len(df_results))
        
        # Compter les spammés (danger ≥ 50%)
        spams = len(df_results[df_results['danger_pct'] >= 50])
        
        with col2:
            ops = len(df_results[df_results['danger_pct'] < 50])
            st.metric("🟢 Opérationnels", ops)
        with col3:
            st.metric("🟡 À vérifier", 0)  # Optionnel
        with col4:
            st.metric("🔴 Spammés", spams)
        
        # Tableau avec pourcentage à la place de risk_score
        st.subheader("📋 Aperçu")
        
        # Nouvelles colonnes : on remplace risk_score par danger_pct
        cols = ['number', 'status', 'danger', 'danger_pct', 'type', 'carrier', 'location']
        df_display = df_results[cols].copy()
        
        # Renommer la colonne pour l'affichage
        df_display = df_display.rename(columns={'danger_pct': 'danger %'})
        
        st.dataframe(df_display, use_container_width=True)
        
        # Détail Numeroinconnu (optionnel)
        with st.expander("🔍 Détail des données Numeroinconnu.fr"):
            for idx, row in df_results.iterrows():
                st.markdown(f"**📞 {row['number']}**")
                
                ni = row.get('numeroinconnu', {})
                
                # 👇 VÉRIFIER LES ERREURS EN PRIORITÉ
                if ni.get('error'):
                    st.error(f"❌ {ni['error']}")
                    st.markdown("---")
                    continue
                
                # 👇 VÉRIFIER LES ÉCHECS (ancienne méthode)
                if ni.get('comments') and any("échouée" in c for c in ni['comments']):
                    st.error(f"❌ Vérification échouée pour {row['number']}")
                    st.markdown("---")
                    continue
                
                # 👇 SI PAS DE DONNÉES
                if not ni or (ni.get('danger_percentage') == 0 and not ni.get('comments')):
                    st.info(f"ℹ️ Aucune information sur ce numéro")
                    st.markdown("---")
                    continue
                
                # 👇 AFFICHAGE NORMAL
                pct = ni.get('danger_percentage', 0)
                
                # Barre de progression
                color = "red" if pct >= 70 else "orange" if pct >= 50 else "green"
                
                st.markdown(f"**Danger : {pct}%**")
                st.markdown(f"""
                    <div style="width:100%; background:#ddd; border-radius:5px;">
                        <div style="width:{pct}%; background:{color}; border-radius:5px; height:20px; text-align:center; color:white;">
                            {pct}%
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                # Statistiques
                stats = []
                if ni.get('visits'):
                    stats.append(f"👁️ {ni['visits']} visites")
                if ni.get('last_visit'):
                    stats.append(f"📅 {ni['last_visit']}")
                if ni.get('comments_count'):
                    stats.append(f"💬 {ni['comments_count']} commentaires")
                
                if stats:
                    st.markdown(" | ".join(stats))
                
                # Commentaires
                if ni.get('comments'):
                    st.markdown("**Commentaires:**")
                    for c in ni['comments']:
                        if not "échouée" in c:
                            st.markdown(f"- {c}")
                
                st.markdown("---")
    # ===== EXPORT SÉLECTIF =====
    if 'verification_results' in st.session_state:
        df_results = st.session_state.verification_results
        
        st.markdown("---")
        st.subheader("📤 Export sélectif")
        
        col1, col2 = st.columns(2)
        with col1:
            option_export = st.radio(
                "Que voulez-vous exporter ?",
                ["📊 Tous les résultats", "🟢 Opérationnels uniquement", "🔴 Spammés uniquement"],
                key="export_radio_final"
            )
        
        # Créer df_export selon le choix
        if 'danger_pct' in df_results.columns:
            if option_export == "🟢 Opérationnels uniquement":
                df_export = df_results[df_results['danger_pct'] < 50].copy()
            elif option_export == "🔴 Spammés uniquement":
                df_export = df_results[df_results['danger_pct'] >= 50].copy()
            else:
                df_export = df_results.copy()
        else:
            df_export = df_results.copy()
        
        with col2:
            st.info(f"📦 {len(df_export)} numéros à exporter")
        
        # Bouton d'export
        csv = df_export.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label=f"📥 Télécharger {len(df_export)} résultats",
            data=csv,
            file_name=f"verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_btn_final"
        )    
# ----------------------------------------------------------------------------
# PAGE GESTION BASE SDA
# ----------------------------------------------------------------------------
elif st.session_state.page == "gestion_sda":
    st.title("📇 Gestion de la Base SDA")
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            st.session_state.page = "accueil"
            st.rerun()
   
     
    # Initialiser le gestionnaire
    if 'sda_manager' not in st.session_state:
        st.session_state.sda_manager = SDAManager()
    
    # Navigation interne
    onglet = st.radio(
        "Section",
        ["📤 Import", "📋 Visualisation", "📊 Statistiques", "🔍 Vérification"],
        horizontal=True
    )
    
    if onglet == "📤 Import":
        st.subheader("Importer des numéros par prestataire")
        
        col1, col2 = st.columns(2)
        with col1:
            prestataire = st.text_input("Nom du prestataire/fournisseur")
        
        with col2:
            uploaded_file = st.file_uploader(
                "Fichier CSV ou Excel",
                type=['csv', 'xlsx', 'xls']
            )
        
        if uploaded_file and prestataire:
            # Aperçu
            if uploaded_file.name.endswith('.csv'):
                df_preview = pd.read_csv(uploaded_file, nrows=5)
            else:
                df_preview = pd.read_excel(uploaded_file, nrows=5)
            
            st.write("Aperçu du fichier :")
            st.dataframe(df_preview)
            
            # Choix de la colonne
            colonne = st.selectbox("Colonne contenant les numéros", df_preview.columns)
            
            if st.button("🚀 IMPORTER", type="primary"):
                with st.spinner("Import en cours..."):
                    resultat = st.session_state.sda_manager.importer_numeros(
                        uploaded_file, prestataire, colonne
                    )
                    if resultat['erreur']:
                        st.error(f"❌ {resultat['erreur']}")
                    else:
                        st.success(f"""
                        ✅ Import terminé !
                        - Prestataire : {resultat['prestataire']}
                        - Numéros dans le fichier : {resultat['total_fichier']}
                        - Numéros importés : {resultat['importes']}
                        """)
    
    elif onglet == "📋 Visualisation":
        st.subheader("📋 Visualisation des numéros par prestataire")
        
        conn = sqlite3.connect('sda_database.db')
        prestataires = pd.read_sql("SELECT nom FROM prestataires", conn)['nom'].tolist()
        
        if prestataires:
            choix = st.selectbox("Choisir un prestataire", ["Tous"] + prestataires)
            
            # Récupérer les données
            if choix == "Tous":
                df = pd.read_sql('''
                    SELECT n.id, n.numero, n.prestataire_id, n.type_ligne, 
                        n.danger_percentage, n.niveau_danger, n.derniere_verification,
                        p.nom as prestataire_nom 
                    FROM numeros_sda n
                    JOIN prestataires p ON n.prestataire_id = p.id
                ''', conn)
            else:
                df = pd.read_sql('''
                    SELECT n.id, n.numero, n.prestataire_id, n.type_ligne,
                        n.danger_percentage, n.niveau_danger, n.derniere_verification,
                        p.nom as prestataire_nom 
                    FROM numeros_sda n
                    JOIN prestataires p ON n.prestataire_id = p.id
                    WHERE p.nom = ?
                ''', conn, params=[choix])
            
            conn.close()
            
            # Filtre rapide sur les échecs techniques
            show_only_failures = st.checkbox("❌ Afficher uniquement les échecs de vérification", value=False)
            if show_only_failures:
                df = df[df['niveau_danger'].fillna('').astype(str).str.startswith('❌')].copy()
                st.info(f"{len(df)} numéro(x) en échec affiché(s).")

            # ===== SÉLECTION MULTIPLE AVEC CHECKBOXES =====
            st.markdown("---")
            st.subheader("✅ Sélectionner des numéros à supprimer")
            
            # Initialiser la colonne de sélection
            if 'select_all' not in st.session_state:
                st.session_state.select_all = False
            
            # Boutons de sélection rapide
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("✓ TOUT SÉLECTIONNER"):
                    st.session_state.select_all = True
                    st.rerun()
            with col2:
                if st.button("✗ TOUT DÉSÉLECTIONNER"):
                    st.session_state.select_all = False
                    st.rerun()
            with col3:
                st.write(f"📊 Total: {len(df)} numéros")
            
            # Créer le DataFrame avec la colonne de sélection
            df_display = df[['numero', 'prestataire_nom', 'danger_percentage', 'niveau_danger', 'derniere_verification']].copy()
            df_display['etat_verification'] = df_display['niveau_danger'].apply(
                lambda x: "❌ Échec" if isinstance(x, str) and x.startswith("❌") else "✅ OK"
            )
            
            # Ajouter la colonne de sélection
            if st.session_state.select_all:
                df_display['Sélectionner'] = True
            else:
                df_display['Sélectionner'] = False
            
            # Afficher le tableau éditable
            edited_df = st.data_editor(
                df_display,
                column_config={
                    "Sélectionner": st.column_config.CheckboxColumn(
                        "✅",
                        help="Cocher pour supprimer",
                        default=False
                    ),
                    "numero": "Numéro",
                    "prestataire_nom": "Prestataire",
                    "danger_percentage": "Danger %",
                    "niveau_danger": "Niveau",
                    "derniere_verification": "Dernière vérif",
                    "etat_verification": "État vérif"
                },
                disabled=['numero', 'prestataire_nom', 'danger_percentage', 'niveau_danger', 'derniere_verification', 'etat_verification'],
                use_container_width=True,
                key="data_editor"
            )
            
            # Récupérer les numéros sélectionnés
            numeros_selectionnes = edited_df[edited_df['Sélectionner'] == True]
            nb_selectionnes = len(numeros_selectionnes)
            
            if nb_selectionnes > 0:
                st.warning(f"📌 {nb_selectionnes} numéro(s) sélectionné(s)")
                
                if st.button("🗑️ SUPPRIMER LA SÉLECTION", type="primary"):
                    st.session_state.confirmation = True
                    st.session_state.numeros_a_supprimer = numeros_selectionnes['numero'].tolist()
                    st.rerun()
            
            # ===== CONFIRMATION DE SUPPRESSION =====
            if 'confirmation' in st.session_state and st.session_state.confirmation:
                st.markdown("---")
                st.error(f"🚨 Confirmation de suppression de {len(st.session_state.numeros_a_supprimer)} numéro(s) :")
                
                # Afficher la liste des numéros à supprimer
                for num in st.session_state.numeros_a_supprimer:
                    st.write(f"- {num}")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ OUI, SUPPRIMER", type="primary"):
                        conn = sqlite3.connect('sda_database.db')
                        cursor = conn.cursor()
                        
                        supprimes = 0
                        for num in st.session_state.numeros_a_supprimer:
                            # Récupérer l'ID du numéro
                            cursor.execute("SELECT id FROM numeros_sda WHERE numero = ?", (num,))
                            result = cursor.fetchone()
                            if result:
                                numero_id = result[0]
                                # Supprimer l'historique
                                cursor.execute("DELETE FROM historique_verifications WHERE numero_id = ?", (numero_id,))
                                # Supprimer le numéro
                                cursor.execute("DELETE FROM numeros_sda WHERE id = ?", (numero_id,))
                                supprimes += 1
                        
                        conn.commit()
                        conn.close()
                        
                        st.success(f"✅ {supprimes} numéro(s) supprimé(s) avec succès !")
                        
                        # Nettoyer la session
                        del st.session_state.confirmation
                        del st.session_state.numeros_a_supprimer
                        st.session_state.select_all = False
                        st.rerun()
                
                with col2:
                    if st.button("❌ NON, ANNULER"):
                        del st.session_state.confirmation
                        del st.session_state.numeros_a_supprimer
                        st.rerun()
            
            # Export de la vue
            st.markdown("---")
            st.subheader("📤 Export")
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Exporter cette vue",
                data=csv,
                file_name=f"sda_{choix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        
        else:
            conn.close()
            st.info("📭 Aucun prestataire pour le moment. Commencez par importer des numéros.")
    
    elif onglet == "📊 Statistiques":
        st.subheader("📊 Tableau de bord SDA")
        
        stats = st.session_state.sda_manager.get_statistiques_globales()
        
        # KPIs principaux
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📞 Total SDA", stats['total'])
        with col2:
            st.metric("✅ Vérifiés", stats['verifies'], f"{stats['verifies']/max(stats['total'],1)*100:.1f}%")
        with col3:
            st.metric("🟢 Opérationnels", stats['sains'])
        with col4:
            st.metric("🔴 Spammés", stats['spams'])
        with col5:
            st.metric("❌ Échecs", stats.get('echecs', 0))
        
        # Graphiques
        col1, col2 = st.columns(2)
        
        with col1:
            # Répartition par statut (camembert)
            if stats['total'] > 0:
                import plotly.express as px
                df_status = pd.DataFrame({
                    'Statut': ['🟢 Opérationnels', '🔴 Spammés', '❌ Échecs'],
                    'Nombre': [stats['sains'], stats['spams'], stats.get('echecs', 0)]
                })
                fig = px.pie(df_status, values='Nombre', names='Statut', 
                            title='Répartition des numéros',
                            color_discrete_sequence=['#2ecc71', '#e74c3c', '#f39c12'])
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Répartition par prestataire (barres)
            if not stats['par_prestataire'].empty:
                fig_bar = px.bar(stats['par_prestataire'], 
                            x='nom', y=['total', 'spams', 'echecs'],
                            title='Numéros par prestataire',
                            barmode='group',
                            labels={'value': 'Nombre', 'nom': 'Prestataire'})
                st.plotly_chart(fig_bar, use_container_width=True)
        
        # Tableau détaillé par prestataire
        st.subheader("🏢 Détail par prestataire")
        
        # Ajouter les colonnes de pourcentage
        df_prest = stats['par_prestataire'].copy()
        df_prest['% spam'] = (df_prest['spams'] / df_prest['total'].replace(0, 1) * 100).round(1).astype(str) + '%'
        df_prest['% échecs'] = (df_prest['echecs'] / df_prest['total'].replace(0, 1) * 100).round(1).astype(str) + '%'
        df_prest['ratio'] = df_prest['spams'].astype(str) + '/' + df_prest['total'].astype(str)
        
        st.dataframe(df_prest[['nom', 'total', 'spams', 'echecs', '% spam', '% échecs', 'ratio']], 
                    use_container_width=True)
        
        # Dernières vérifications
        st.subheader("🕒 Dernières vérifications")
        
        conn = sqlite3.connect('sda_database.db')
        dernieres = pd.read_sql('''
            SELECT n.numero, p.nom as prestataire, 
                h.danger_percentage, h.niveau_danger,
                h.date_verification
            FROM historique_verifications h
            JOIN numeros_sda n ON h.numero_id = n.id
            JOIN prestataires p ON n.prestataire_id = p.id
            ORDER BY h.date_verification DESC
            LIMIT 20
        ''', conn)
        conn.close()
        
        if not dernieres.empty:
            st.dataframe(dernieres, use_container_width=True)
        else:
            st.info("Aucune vérification pour l'instant")

    elif onglet == "🔍 Vérification":
        st.subheader("Vérification des numéros")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🎯 Vérification manuelle")
            
            # Choix du mode
            mode_verif = st.radio(
                "Sélectionner les numéros à vérifier",
                ["Tous les numéros", "Par prestataire", "Numéro spécifique"]
            )
            
            if mode_verif == "Par prestataire":
                conn = sqlite3.connect('sda_database.db')
                prestataires = pd.read_sql("SELECT nom FROM prestataires", conn)['nom'].tolist()
                conn.close()
                
                if prestataires:
                    choix_prest = st.selectbox("Choisir un prestataire", prestataires)
                else:
                    st.warning("Aucun prestataire trouvé")
                    choix_prest = None
            
            elif mode_verif == "Numéro spécifique":
                numero_spec = st.text_input("Entrer le numéro à vérifier")
            
            # Bouton de vérification
            force_recheck = st.checkbox("🔁 Forcer la re-vérification (même déjà vérifiés)", value=False)
            if st.button("🚀 LANCER VÉRIFICATION", type="primary"):
                with st.spinner("Vérification en cours..."):
                    if mode_verif == "Tous les numéros":
                        resultat = st.session_state.sda_manager.verifier_lot(limite=None, force=force_recheck)
                    elif mode_verif == "Par prestataire" and choix_prest:
                        resultat = st.session_state.sda_manager.verifier_lot(choix_prest, limite=None, force=force_recheck)
                    elif mode_verif == "Numéro spécifique" and numero_spec:
                        # Chercher l'ID du numéro
                        conn = sqlite3.connect('sda_database.db')
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM numeros_sda WHERE numero = ?", (numero_spec,))
                        result = cursor.fetchone()
                        conn.close()
                        
                        if result:
                            st.session_state.sda_manager.verifier_et_mettre_a_jour(result[0], numero_spec)
                            resultat = {"message": f"✅ Numéro {numero_spec} vérifié", "verifies": 1}
                        else:
                            resultat = {"message": "❌ Numéro non trouvé dans la base", "verifies": 0}
                    
                    st.success(resultat['message'])
        
        with col2:
            st.markdown("### ⏰ Vérification programmée")
            st.info("""
            **Fonctionnalité à venir :**
            - Planification quotidienne
            - Alertes automatiques
            - Rapport par email
            """)
            
            heure = st.time_input("Heure de vérification quotidienne", value=datetime.now().time())
            
            if st.button("⏰ PROGRAMMER"):
                st.success(f"✅ Vérification programmée tous les jours à {heure}")


# ----------------------------------------------------------------------------
# PAGE CONFIGURATION ALERTES
# ----------------------------------------------------------------------------
elif st.session_state.page == "config_alertes":
    st.title("📧 Configuration des alertes email")
    
    # Bouton retour
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← Retour", use_container_width=True):
            st.session_state.page = "accueil"
            st.rerun()
    
    # Afficher un message si une config existe
    if st.session_state.config_chargee:
        st.success("✅ Configuration SMTP chargée automatiquement")
    
    # Formulaire de configuration
    config = st.session_state.alerter.config if st.session_state.alerter else None
    with st.form("form_config_email"):
        st.subheader("📧 Configuration SMTP")
        
        # Valeurs par défaut depuis la config existante
        default_smtp = st.session_state.alerter.config['smtp_server'] if st.session_state.alerter.config else "smtp.gmail.com"
        default_port = st.session_state.alerter.config['smtp_port'] if st.session_state.alerter.config else 587
        default_email = st.session_state.alerter.config['email'] if st.session_state.alerter.config else ""
        default_dest = '\n'.join(st.session_state.alerter.config['destinataires']) if st.session_state.alerter.config else ""
        
        col1, col2 = st.columns(2)
        with col1:
            smtp_server = st.text_input("Serveur SMTP", value=default_smtp)
            email = st.text_input("Adresse email expéditrice", value=default_email)
        
        with col2:
            smtp_port = st.number_input("Port SMTP", value=default_port)
            password = st.text_input("Mot de passe", type="password", value= config['password'] if config else "" )
        
        st.subheader("📬 Destinataires")
        destinataires = st.text_area(
            "Adresses email (une par ligne)",
            value=default_dest,
            placeholder="alert@example.com\nresponsable@example.com"
        )
        
        if st.form_submit_button("💾 Enregistrer la configuration"):
            liste_dest = [d.strip() for d in destinataires.split('\n') if d.strip()]
            
            # Sauvegarder dans la base
            st.session_state.alerter.sauvegarder_config(
                smtp_server, smtp_port, email, password, liste_dest
            )
            st.session_state.config_chargee = True
            st.success("✅ Configuration enregistrée et sauvegardée !")

    #  NOUVELLE SECTION PLANIFICATION
    st.markdown("---")
    st.subheader("⏰ Planification automatique")

    col1, col2 = st.columns(2)
    with col1:
        # Afficher l'heure actuelle programmée
        if st.session_state.scheduler.heure_programmee:
            st.info(f"⏰ Actuellement programmé à : {st.session_state.scheduler.heure_programmee}")
        
        # Heure par défaut = dernière programmation ou 08:00
        heure_defaut = datetime.strptime(
            st.session_state.scheduler.heure_programmee if st.session_state.scheduler.heure_programmee else "08:00", 
            "%H:%M"
        ).time()
        
        nouvelle_heure = st.time_input("Heure de vérification quotidienne", value=heure_defaut)
        
        if st.button("✅ PROGRAMMER", type="primary"):
            heure_str = nouvelle_heure.strftime("%H:%M")
            st.session_state.scheduler.programmer(heure_str)
            st.success(f"✅ Vérification programmée tous les jours à {heure_str}")
            st.rerun()

    with col2:
        if st.button("⏹️ ARRÊTER LA PLANIFICATION"):
            if st.session_state.scheduler:
                st.session_state.scheduler.arreter()
                st.session_state.scheduler.heure_programmee = None
                st.warning("⏸️ Planification arrêtée")
                st.rerun()
        
        if st.button("🚀 TESTER MAINTENANT"):
            with st.spinner("Exécution de la vérification..."):
                st.session_state.scheduler.job_verification()
                st.success("✅ Vérification terminée !")
    
    # Dans la page ALERTES, remplace la section test par :

    st.markdown("---")
    st.subheader("🔍 Test avec vrais spams")

    # Initialiser la variable de session pour les spams
    if 'nouveaux_spams' not in st.session_state:
        st.session_state.nouveaux_spams = None

    if st.button("🔍 Vérifier les nouveaux spams"):
        with st.spinner("Recherche des nouveaux spams..."):
            nouveaux = st.session_state.alerter.verifier_nouveaux_spams()
            
            if not nouveaux.empty:
                st.session_state.nouveaux_spams = nouveaux
                st.success(f"🚨 {len(nouveaux)} nouveaux spams détectés !")
                st.dataframe(nouveaux, use_container_width=True)
            else:
                st.session_state.nouveaux_spams = None
                st.info("✅ Aucun nouveau spam détecté")

    # Afficher le bouton d'envoi seulement si des spams sont stockés
    if st.session_state.nouveaux_spams is not None and not st.session_state.nouveaux_spams.empty:
        if st.button("📨 Envoyer l'alerte pour ces spams"):
            with st.spinner("Envoi en cours..."):
                resultat = st.session_state.alerter.envoyer_alerte_spams(st.session_state.nouveaux_spams)
                if resultat:
                    st.success(f"✅ Alerte envoyée pour {len(st.session_state.nouveaux_spams)} spams !")
                    # Optionnel : effacer après envoi
                    # st.session_state.nouveaux_spams = None
                else:
                    st.error("❌ Échec de l'envoi")

