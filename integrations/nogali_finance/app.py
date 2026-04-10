import streamlit as st
import pandas as pd
import plotly.express as px
import json
import os
import tempfile
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import re

st.set_page_config(page_title="Nogali - Rapport Financier", layout="wide")

# ==================== STYLES ====================
st.markdown("""
<style>
    /* STYLE DES ONGLETS CUSTOM EN CADRANS */
    button[role="tab"], div[data-testid="stTabs"] button[data-baseweb="tab"] {
        flex: 1 !important;
        text-align: center !important;
        background-color: rgba(255, 255, 255, 0.03) !important;
        border-radius: 10px 10px 0 0 !important;
        padding: 5px 15px !important;
        margin: 0 5px !important;
        border: none !important;
        border-top: 4px solid #333 !important;
        transition: all 0.2s ease !important;
    }
    button[role="tab"]:nth-child(1), div[data-testid="stTabs"] button[data-baseweb="tab"]:nth-child(1) { border-top: 4px solid #00f2fe !important; }
    button[role="tab"]:nth-child(2), div[data-testid="stTabs"] button[data-baseweb="tab"]:nth-child(2) { border-top: 4px solid #ff4b4b !important; }
    button[role="tab"]:nth-child(3), div[data-testid="stTabs"] button[data-baseweb="tab"]:nth-child(3) { border-top: 4px solid #f093fb !important; }
    
    button[role="tab"]:hover {
        background-color: rgba(255, 255, 255, 0.08) !important;
    }
    button[role="tab"][aria-selected="true"] {
        background-color: rgba(255, 255, 255, 0.15) !important;
        box-shadow: 0 -4px 15px rgba(0, 0, 0, 0.3) !important;
    }
    button[role="tab"] p { font-weight: bold !important; font-size: 1.1rem !important; }
    .stColumn { padding: 0 5px !important; }
    div[data-testid="stMetric"] { width: 100%; min-width: 100px; }
    div[data-testid="stMetricValue"] { font-size: 1.2rem !important; }
    .stDataFrame { font-size: 12px; }
    .kpi-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 20px;
        padding: 1rem;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin: 0.5rem;
        transition: transform 0.2s;
        height: 120px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .kpi-card:hover { transform: translateY(-3px); }
    .kpi-card.revenus { background: linear-gradient(135deg, #11998e, #38ef7d); }
    .kpi-card.charges { background: linear-gradient(135deg, #eb3349, #f45c43); }
    .kpi-card.benefice { background: linear-gradient(135deg, #4facfe, #00f2fe); }
    .kpi-card.repartition { background: linear-gradient(135deg, #f093fb, #f5576c); }
    .kpi-label { color: white; font-size: 0.9rem; font-weight: 500; margin-bottom: 0.5rem; }
    .kpi-value { color: white; font-size: 1.8rem; font-weight: bold; }
    .kpi-sub { color: rgba(255,255,255,0.8); font-size: 0.7rem; margin-top: 0.25rem; }
    footer { display: none; }
    
    .status-card {
        border-radius: 10px;
        padding: 12px 15px;
        margin-bottom: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: all 0.2s;
    }
    .status-card:hover { transform: translateX(5px); }
    /* Mode sombre / clair dynamique */
    .status-paye { background-color: rgba(40, 167, 69, 0.15); border-left: 5px solid #28a745; }
    .status-avance { background-color: rgba(255, 193, 7, 0.15); border-left: 5px solid #ffc107; }
    .status-attente { background-color: rgba(220, 53, 69, 0.15); border-left: 5px solid #dc3545; }
    
    .status-paye .status-badge { background: rgba(40, 167, 69, 0.2); color: var(--text-color); border: 1px solid rgba(40, 167, 69, 0.5); }
    .status-avance .status-badge { background: rgba(255, 193, 7, 0.2); color: var(--text-color); border: 1px solid rgba(255, 193, 7, 0.5); }
    .status-attente .status-badge { background: rgba(220, 53, 69, 0.2); color: var(--text-color); border: 1px solid rgba(220, 53, 69, 0.5); }

    .status-icon { font-size: 1.5rem; margin-right: 10px; }
    .status-info { flex: 2; min-width: 100px; }
    .status-montant { font-weight: bold; font-size: 1.2rem; }
    .status-actions { display: flex; gap: 10px; align-items: center; }
    .status-badge {
        padding: 3px 8px;
        border-radius: 15px;
        font-size: 0.7rem;
        font-weight: bold;
        white-space: nowrap;
    }
</style>
""", unsafe_allow_html=True)

# ==================== CONFIGURATION ====================
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Q4wmTglIQu1c-rkc5SicNAlO6RPz9wm7fXe0JxzrjQg/edit"
CREDENTIALS_FILE = "credentials.json"
CONFIG_FILE = "exclusivite_config.json"
LAST_UPDATE_FILE = "last_update.json"
STATUS_FILE = "status_nogali.json"
CORRECTIONS_FILE = "corrections_nogali.json"
PREUVES_DIR = "preuves"

os.makedirs(PREUVES_DIR, exist_ok=True)

# Override optionnel via Streamlit secrets (hébergement cloud)
try:
    if "SHEET_URL" in st.secrets:
        SHEET_URL = st.secrets["SHEET_URL"]
except Exception:
    pass


def _get_credentials_file_path():
    """
    Retourne le chemin du fichier de credentials à utiliser.
    Priorité:
    1) credentials.json local (mode dev local)
    2) st.secrets['gcp_service_account'] (mode Streamlit Cloud)
    """
    if os.path.exists(CREDENTIALS_FILE):
        return CREDENTIALS_FILE

    try:
        if "gcp_service_account" in st.secrets:
            creds = dict(st.secrets["gcp_service_account"])
            tmp_dir = tempfile.gettempdir()
            tmp_path = os.path.join(tmp_dir, "nogali_gcp_service_account.json")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(creds, f, ensure_ascii=False)
            return tmp_path
    except Exception:
        pass

    return None

# ==================== GESTION DES CORRECTIONS MANUELLES ====================
def charger_corrections():
    if os.path.exists(CORRECTIONS_FILE):
        with open(CORRECTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def sauvegarder_corrections(corrections):
    with open(CORRECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(corrections, f, ensure_ascii=False, indent=4)

def appliquer_corrections(df_revenus, df_charges, annee, mois, corrections):
    """Applique les corrections manuelles sur les DataFrames revenus et charges."""
    cle_base = f"{annee}_{mois}"
    df_rev = df_revenus.copy()
    df_chr = df_charges.copy()
    for cle, valeur in corrections.items():
        if cle.startswith(f"rev_{cle_base}_"):
            site = cle.replace(f"rev_{cle_base}_", "").replace("_", " ")
            if 'Site' in df_rev.columns:
                df_rev.loc[df_rev['Site'] == site, 'Montant'] = valeur
            else:
                df_rev = pd.concat([df_rev, pd.DataFrame([{'Site': site, 'Montant': valeur}])], ignore_index=True)
        elif cle.startswith(f"chr_{cle_base}_"):
            prest = cle.replace(f"chr_{cle_base}_", "").replace("_", " ")
            if 'Prestataire' in df_chr.columns:
                df_chr.loc[df_chr['Prestataire'] == prest, 'Montant'] = valeur
            else:
                df_chr = pd.concat([df_chr, pd.DataFrame([{'Prestataire': prest, 'Montant': valeur}])], ignore_index=True)
    return df_rev, df_chr

# ==================== GESTION DU CACHE ====================
def get_last_update():
    if os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, 'r') as f:
            return json.load(f).get('last_update', 0)
    return 0

def set_last_update(timestamp):
    with open(LAST_UPDATE_FILE, 'w') as f:
        json.dump({'last_update': timestamp}, f)

# ==================== GESTION DES STATUTS ====================
def charger_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def sauvegarder_status(status):
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=4)

# ==================== FONCTIONS DE CONVERSION ====================
def clean_montant_revenu(val):
    """Convertit un montant de revenu en float"""
    if pd.isna(val):
        return 0
    
    if isinstance(val, (int, float)):
        return float(val)
    
    val_str = str(val)
    val_str = val_str.replace('€', '')
    val_str = re.sub(r'\s+', '', val_str)
    
    if ',' in val_str and '.' in val_str:
        if val_str.rfind(',') > val_str.rfind('.'):
            val_str = val_str.replace('.', '').replace(',', '.')
        else:
            val_str = val_str.replace(',', '')
    else:
        if ',' in val_str:
            val_str = val_str.replace(',', '.')
    
    try:
        return float(val_str)
    except:
        return 0

def clean_montant_charge(val, prestataire):
    """Convertit un montant de charge en float selon le prestataire"""
    if pd.isna(val):
        return 0
    
    if isinstance(val, (int, float)):
        return float(val)
    
    val_str = str(val)
    val_str = val_str.replace('€', '')
    val_str = re.sub(r'\s+', '', val_str)
    
    if ',' in val_str and '.' in val_str:
        if val_str.rfind(',') > val_str.rfind('.'):
            val_str = val_str.replace('.', '').replace(',', '.')
        else:
            val_str = val_str.replace(',', '')
    else:
        if ',' in val_str:
            val_str = val_str.replace(',', '.')
    
    try:
        return float(val_str)
    except:
        return 0

# ==================== CHARGEMENT ====================
@st.cache_data(ttl=86400)
def charger_depuis_api():
    creds_path = _get_credentials_file_path()
    if not creds_path:
        return pd.DataFrame(), pd.DataFrame()
    
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SHEET_URL)
        
        ws_revenus = spreadsheet.worksheet("Archives_Globales")
        data_revenus = ws_revenus.get_all_records(numericise_ignore=['all'])
        df_revenus = pd.DataFrame(data_revenus)
        
        ws_charges = spreadsheet.worksheet("Suivi_Financier")
        data_charges = ws_charges.get_all_records(numericise_ignore=['all'])
        df_charges = pd.DataFrame(data_charges)
        
        set_last_update(time.time())
        return df_revenus, df_charges
        
    except Exception as e:
        st.error(f"Erreur API : {e}")
        return pd.DataFrame(), pd.DataFrame()

# ==================== TRAITEMENT REVENUS MIAMBOO ====================
def traiter_revenus_miamboo(df):
    if df.empty:
        return df
    
    df.columns = df.columns.str.strip()
    
    if 'Montant Facture Final' in df.columns:
        df['Montant'] = df['Montant Facture Final'].apply(clean_montant_revenu)
    else:
        return pd.DataFrame()
    
    if 'Mois_Facture' in df.columns:
        df['Mois'] = df['Mois_Facture'].astype(str).str.lower()
    else:
        df['Mois'] = 'inconnu'
    
    if 'annee' in df.columns:
        df['Annee'] = pd.to_numeric(df['annee'], errors='coerce').fillna(0).astype(int)
    else:
        df['Annee'] = 0
    
    if 'ID_Site' in df.columns:
        df['Site'] = df['ID_Site'].astype(str)
    else:
        df['Site'] = 'Inconnu'
    
    df = df[df['Mois'] != 'inconnu']
    df = df[df['Montant'] > 0]
    
    return df

# ==================== TRAITEMENT REVENUS RINGOVER ====================
def traiter_revenus_ringover(df):
    if df.empty:
        return pd.DataFrame()
    
    df.columns = df.columns.str.strip()
    
    if 'Type_Flux' in df.columns and 'Type_Service' in df.columns:
        df = df[(df['Type_Flux'] == 'Revenu') & (df['Type_Service'] == 'Ringover')].copy()
    else:
        return pd.DataFrame()
    
    if 'Montant' in df.columns:
        df['Montant'] = df['Montant'].apply(clean_montant_revenu)
    else:
        return pd.DataFrame()
    
    if 'Mois' in df.columns:
        df['Mois'] = df['Mois'].astype(str).str.lower()
    else:
        df['Mois'] = 'inconnu'
        
    if 'Année' in df.columns:
        df['Annee'] = pd.to_numeric(df['Année'], errors='coerce').fillna(0).astype(int)
    else:
        df['Annee'] = 0
    
    if 'Nom_Prestataire' in df.columns:
        df['Site'] = df['Nom_Prestataire'].astype(str)
        df['Site'] = df['Site'].replace({
            'Gabrielle': 'Nogali2',
            'Francine': 'Nogali3',
            'Malick': 'Nogali5',
            'Manuela': 'Nogali6',
            'Akili': 'Akili'
        })
    else:
        df['Site'] = 'Inconnu'
    
    df = df[df['Mois'] != 'inconnu']
    df = df[df['Montant'] > 0]
    
    return df

# ==================== TRAITEMENT CHARGES ====================
def traiter_charges(df):
    if df.empty:
        return df
    
    df.columns = df.columns.str.strip()
    
    if 'Type_Flux' in df.columns:
        df = df[df['Type_Flux'] == 'Charge'].copy()
    
    if 'Montant' not in df.columns:
        return pd.DataFrame()
    
    if 'Nom_Prestataire' in df.columns:
        df['Prestataire'] = df['Nom_Prestataire'].astype(str)
        df['Prestataire'] = df['Prestataire'].replace({'Coffee': 'Ceffage'})
    else:
        df['Prestataire'] = 'Inconnu'
    
    # Conversion des montants avec la fonction spécifique
    def convertir_ligne(row):
        return clean_montant_charge(row['Montant'], row['Prestataire'])
    
    df['Montant'] = df.apply(convertir_ligne, axis=1)
    
    if 'Mois' in df.columns:
        df['Mois'] = df['Mois'].astype(str).str.lower()
    else:
        df['Mois'] = 'inconnu'
    
    if 'Année' in df.columns:
        df['Annee'] = pd.to_numeric(df['Année'], errors='coerce').fillna(0).astype(int)
    else:
        df['Annee'] = 0
    
    df = df[df['Mois'] != 'inconnu']
    df = df[df['Montant'] > 0]
    
    return df

# ==================== LISTE DES PAIEMENTS ====================
def afficher_liste_paiements(items, title, type_transaction):
    st.markdown(f"### {title}")
    
    if not items:
        st.info(f"Aucun {type_transaction} pour cette période")
        return
    
    for item in items:
        transaction_id = item['id']
        montant = item['montant']
        nom = item['nom']
        status_actuel = item.get('status', 'en_attente')
        montant_avance = item.get('montant_avance', 0)
        av1_val = item.get('av1', 0)
        av2_val = item.get('av2', 0)
        av3_val = item.get('av3', 0)
        preuve_nom = item.get('preuve_nom', None)
        
        if status_actuel == 'paye':
            status_class = "status-paye"
            status_text = "✅ Payé"
        elif status_actuel == 'avance':
            status_class = "status-avance"
            reste = montant - montant_avance
            av_texts = []
            if av1_val > 0: av_texts.append(f"{av1_val:.0f}€")
            if av2_val > 0: av_texts.append(f"{av2_val:.0f}€")
            if av3_val > 0: av_texts.append(f"{av3_val:.0f}€")
            detail_str = " + ".join(av_texts) if len(av_texts) > 1 else ""
            if detail_str: detail_str = f" ({detail_str})"
            status_text = f"💰 Avance: {montant_avance:.2f} €{detail_str} | Reste: {reste:.2f} €"
        else:
            status_class = "status-attente"
            status_text = "⏳ En attente"
        
        with st.container():
            st.markdown(f"""
            <div class="status-card {status_class}" style="flex-direction: column; align-items: stretch; gap: 12px; padding: 15px;">
                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                    <div style="display: flex; align-items: center;">
                        <div class="status-icon" style="margin-right: 12px;">{item['icon']}</div>
                        <div class="status-info" style="line-height: 1.3;">
                            <strong style="font-size: 0.95rem;">{nom}</strong><br>
                            <small style="opacity: 0.8;">{item['mois']} {item['annee']}</small>
                        </div>
                    </div>
                    <div class="status-montant" style="white-space: nowrap; margin-left: 10px;">{montant:.2f} €</div>
                </div>
                <div class="status-actions" style="margin: 0;">
                    <span class="status-badge" style="display: block; width: 100%; text-align: center; white-space: normal; padding: 6px 10px; border-radius: 8px;">{status_text}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            with st.expander(f"✏️ Modifier le statut - {nom}", expanded=False):
                nouveau_statut = st.selectbox(
                    "📌 Statut", 
                    options=["en_attente", "avance", "paye"],
                    format_func=lambda x: "⏳ En attente" if x == 'en_attente' else "💰 Avance" if x == 'avance' else "✅ Payé",
                    index=0 if status_actuel == 'en_attente' else 1 if status_actuel == 'avance' else 2,
                    key=f"status_{transaction_id}"
                )
                
                if nouveau_statut == 'avance':
                    st.markdown("**Détails des acomptes (jusqu'à 3 saisies simultanées)**")
                    cav1, cav2, cav3 = st.columns(3)
                    with cav1: av1 = st.number_input("💶 Acc 1", min_value=0.0, max_value=float(montant), value=float(av1_val), step=10.0, key=f"av1_{transaction_id}")
                    with cav2: av2 = st.number_input("💶 Acc 2", min_value=0.0, max_value=float(montant), value=float(av2_val), step=10.0, key=f"av2_{transaction_id}")
                    with cav3: av3 = st.number_input("💶 Acc 3", min_value=0.0, max_value=float(montant), value=float(av3_val), step=10.0, key=f"av3_{transaction_id}")
                    avance_montant = av1 + av2 + av3
                else:
                    avance_montant = 0.0
                    av1 = av2 = av3 = 0.0
                    
                uploaded_file = st.file_uploader(
                    "📎 Joindre une preuve (PDF)", 
                    type=["pdf"], 
                    key=f"pdf_{transaction_id}"
                )
                
                st.write("")
                if st.button("💾 Enregistrer les modifications", key=f"save_{transaction_id}", use_container_width=True):
                    status_data = charger_status()
                    status_data[transaction_id] = {
                        'statut': nouveau_statut, 'montant_avance': avance_montant if nouveau_statut == 'avance' else 0,
                        'av1': av1 if nouveau_statut == 'avance' else 0,
                        'av2': av2 if nouveau_statut == 'avance' else 0,
                        'av3': av3 if nouveau_statut == 'avance' else 0,
                        'montant_total': montant, 'date_modification': datetime.now().isoformat(),
                        'preuve_nom': uploaded_file.name if uploaded_file else preuve_nom
                    }
                    sauvegarder_status(status_data)
                    if uploaded_file:
                        pdf_path = os.path.join(PREUVES_DIR, f"{transaction_id}_{uploaded_file.name}")
                        with open(pdf_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                    st.success(f"✅ Statut mis à jour : {nouveau_statut}")
                    st.rerun()
                if preuve_nom:
                    st.caption(f"📎 Preuve existante : {preuve_nom}")

# ==================== CALCULS ====================
def calculer_revenus_par_site(df, annee, mois):
    revenus = df[(df['Annee'] == annee) & (df['Mois'] == mois.lower())]
    if revenus.empty:
        return pd.DataFrame()
    result = revenus.groupby('Site')['Montant'].sum().reset_index()
    result.columns = ['Site', 'Montant']
    return result.sort_values('Montant', ascending=False)

def calculer_revenus_ringover_par_agent(df, annee, mois):
    """Retourne un DataFrame avec le détail des revenus Ringover par agent."""
    if df.empty:
        return pd.DataFrame()
    revenus = df[(df['Annee'] == annee) & (df['Mois'] == mois.lower())]
    if revenus.empty:
        return pd.DataFrame()
    result = revenus.groupby('Site')['Montant'].sum().reset_index()
    result.columns = ['Agent', 'Montant']
    return result.sort_values('Montant', ascending=False)

def calculer_charges_par_prestataire(df, annee, mois):
    charges = df[(df['Annee'] == annee) & (df['Mois'] == mois.lower())]
    prestataires = ['Inextrix', 'Ceffage', 'Coriolis', 'Contabo', 'Ringover']
    if charges.empty:
        return pd.DataFrame({'Prestataire': prestataires, 'Montant': [0]*len(prestataires)})
    result = charges.groupby('Prestataire')['Montant'].sum().reset_index()
    result.columns = ['Prestataire', 'Montant']
    for p in prestataires:
        if p not in result['Prestataire'].values:
            result = pd.concat([result, pd.DataFrame({'Prestataire': [p], 'Montant': [0]})], ignore_index=True)
    return result.sort_values('Montant', ascending=False)

def calculer_synthese(df_revenus_miamboo, df_revenus_ringover, df_charges, annee, mois):
    mois_lower = mois.lower()
    
    revenus_miamboo_mois = df_revenus_miamboo[(df_revenus_miamboo['Annee'] == annee) & (df_revenus_miamboo['Mois'] == mois_lower)]
    total_revenus_miamboo = revenus_miamboo_mois['Montant'].sum()
    
    revenus_ringover_mois = df_revenus_ringover[(df_revenus_ringover['Annee'] == annee) & (df_revenus_ringover['Mois'] == mois_lower)]
    total_revenus_ringover = revenus_ringover_mois['Montant'].sum()
    
    total_revenus = total_revenus_miamboo + total_revenus_ringover
    
    charges_mois = df_charges[(df_charges['Annee'] == annee) & (df_charges['Mois'] == mois_lower)]
    
    charges_miamboo = 0
    charges_ringover = 0
    for _, row in charges_mois.iterrows():
        if 'Ringover' in row['Prestataire']:
            charges_ringover += row['Montant']
        else:
            charges_miamboo += row['Montant']
    
    total_charges = charges_miamboo + charges_ringover
    
    benefice_miamboo = total_revenus_miamboo - charges_miamboo
    benefice_ringover = total_revenus_ringover - charges_ringover
    
    part_nogali = benefice_ringover + (benefice_miamboo * 0.5)
    part_aetech = benefice_miamboo * 0.5
    
    return {
        'revenus': total_revenus,
        'charges': total_charges,
        'charges_miamboo': charges_miamboo,
        'charges_ringover': charges_ringover,
        'benefice_miamboo': benefice_miamboo,
        'benefice_ringover': benefice_ringover,
        'part_nogali': part_nogali,
        'part_aetech': part_aetech,
        'revenus_miamboo': total_revenus_miamboo,
        'revenus_ringover': total_revenus_ringover
    }

# ==================== INTERFACE ====================
st.title("💰 Nogali - Rapport Financier")
st.markdown("Centre d'appel • Suivi des revenus (licences Miamboo) et charges (prestataires)")

with st.spinner("Chargement des données depuis Google Sheets..."):
    df_revenus_raw, df_charges_raw = charger_depuis_api()

if df_revenus_raw.empty:
    st.warning("Aucune donnée de revenus chargée.")
    st.stop()

revenus_miamboo = traiter_revenus_miamboo(df_revenus_raw)
revenus_ringover = traiter_revenus_ringover(df_charges_raw)
df_charges = traiter_charges(df_charges_raw)

# ── Exception AKILI : montant pris depuis Suivi_Financier, pas Archives_Globales ──
# Archives_Globales peut avoir N lignes par mois pour Akili (une par facture).
# On supprime toutes ces lignes et on les remplace par UNE seule ligne
# avec le total de Suivi_Financier pour éviter la multiplication des montants.
if not df_charges_raw.empty and not revenus_miamboo.empty and 'Site' in revenus_miamboo.columns:
    try:
        df_sf = df_charges_raw.copy()
        df_sf.columns = df_sf.columns.str.strip()
        if 'Nom_Prestataire' in df_sf.columns and 'Montant' in df_sf.columns:
            akili_sf = df_sf[
                df_sf['Nom_Prestataire'].astype(str).str.strip().str.lower() == 'akili'
            ].copy()
            if not akili_sf.empty:
                akili_sf['Montant'] = akili_sf['Montant'].apply(clean_montant_revenu)
                akili_sf['Mois_norm'] = akili_sf['Mois'].astype(str).str.lower()
                if 'Année' in akili_sf.columns:
                    akili_sf['Annee_norm'] = pd.to_numeric(akili_sf['Année'], errors='coerce').fillna(0).astype(int)
                else:
                    akili_sf['Annee_norm'] = 0
                # Agréger : 1 total par mois/année dans Suivi_Financier
                akili_totaux = akili_sf.groupby(['Mois_norm', 'Annee_norm'])['Montant'].sum().reset_index()
                for _, row_tot in akili_totaux.iterrows():
                    if row_tot['Montant'] > 0:
                        # 1. Supprimer TOUTES les lignes Akili de ce mois dans revenus_miamboo
                        mask_del = (
                            (revenus_miamboo['Site'].astype(str).str.strip().str.lower() == 'akili') &
                            (revenus_miamboo['Mois'] == row_tot['Mois_norm']) &
                            (revenus_miamboo['Annee'] == row_tot['Annee_norm'])
                        )
                        revenus_miamboo = revenus_miamboo[~mask_del].copy()
                        # 2. Ajouter UNE seule ligne Akili avec le bon total Suivi_Financier
                        new_row = pd.DataFrame([{
                            'Site': 'Akili',
                            'Montant': row_tot['Montant'],
                            'Mois': row_tot['Mois_norm'],
                            'Annee': int(row_tot['Annee_norm'])
                        }])
                        revenus_miamboo = pd.concat([revenus_miamboo, new_row], ignore_index=True)
    except Exception:
        pass  # En cas d'erreur, on garde la valeur d'origine sans bloquer l'appli


# CALCULS GLOBAUX POUR LES DROPDOWNS
revenus_miamboo['Mois'] = revenus_miamboo['Mois'].astype(str).str.lower()
annees_set = set()
if not revenus_miamboo.empty: annees_set.update(revenus_miamboo['Annee'].unique())
if not revenus_ringover.empty: annees_set.update(revenus_ringover['Annee'].unique())
if not df_charges.empty: annees_set.update(df_charges['Annee'].unique())
annees_dispos = sorted(list(annees_set))
if not annees_dispos: annees_dispos = [2026]

with st.sidebar:
    st.header("🔄 Synchronisation")
    last = get_last_update()
    if last > 0:
        st.info(f"📅 Dernière synchro : {datetime.fromtimestamp(last).strftime('%d/%m/%Y %H:%M')}")
    if st.button("🔄 Mettre à jour", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    
    st.header("🔍 Période Analysée")
    st.caption("Filtre partagé pour la Vue Mensuelle et le Suivi Paiement")
    annee_choisie = st.selectbox("📅 Année", annees_dispos, index=len(annees_dispos)-1)
    
    mois_ordre = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
    def trier_mois(mois):
        try: return mois_ordre.index(mois)
        except: return 999
        
    mois_set = set()
    if not revenus_miamboo.empty: mois_set.update(revenus_miamboo[revenus_miamboo['Annee'] == annee_choisie]['Mois'].unique())
    if not revenus_ringover.empty: mois_set.update(revenus_ringover[revenus_ringover['Annee'] == annee_choisie]['Mois'].unique())
    if not df_charges.empty: mois_set.update(df_charges[df_charges['Annee'] == annee_choisie]['Mois'].unique())
    mois_avec_donnees = sorted(list(mois_set), key=trier_mois)
    if not mois_avec_donnees: mois_avec_donnees = ['inconnu']
    
    mois_choisi = st.selectbox("📆 Mois", mois_avec_donnees, format_func=lambda x: str(x).capitalize())
    
    st.divider()
    st.header("📊 Aperçu Global")
    st.caption(f"Revenus Miamboo : {len(revenus_miamboo)} lignes")
    st.caption(f"Revenus Ringover : {len(revenus_ringover)} lignes")
    st.caption(f"Charges : {len(df_charges)} lignes")

# ================= TABS =================
tab_dashboard, tab_mensuel, tab_suivi = st.tabs([
    "📊 Tableau de Bord", 
    "📅 Vue Mensuelle", 
    "💳 Suivi Paiements"
])

# Restrictions par modules finance (pilotées par la session centrale)
role_user = st.session_state.get("role", "user")
permissions_user = st.session_state.get("permissions", {})
is_admin_like = role_user in ["admin", "super_admin"]

can_fin_dashboard = is_admin_like or bool(permissions_user.get("access_fin_dashboard", True))
can_fin_mensuel = is_admin_like or bool(permissions_user.get("access_fin_mensuel", True))
can_fin_suivi = is_admin_like or bool(permissions_user.get("access_fin_suivi", True))

if not can_fin_dashboard:
    st.error("⛔ Accès refusé: module Finance - Tableau de bord.")
    st.stop()

hidden_tabs_css = []
if not can_fin_mensuel:
    hidden_tabs_css.append("button[role='tab']:nth-child(2){display:none !important;}")
if not can_fin_suivi:
    hidden_tabs_css.append("button[role='tab']:nth-child(3){display:none !important;}")
if hidden_tabs_css:
    st.markdown(f"<style>{''.join(hidden_tabs_css)}</style>", unsafe_allow_html=True)

# == CALCULS COMMUNS DU MOIS ==
synthese = calculer_synthese(revenus_miamboo, revenus_ringover, df_charges, annee_choisie, mois_choisi)
revenus_par_site = calculer_revenus_par_site(revenus_miamboo, annee_choisie, mois_choisi)
charges_par_prestataire = calculer_charges_par_prestataire(df_charges, annee_choisie, mois_choisi)



status_data = charger_status()


revenus_items = []
for _, row in revenus_par_site.iterrows():
    transaction_id = f"revenu_{annee_choisie}_{mois_choisi}_{row['Site'].replace(' ', '_')}"
    statut_info = status_data.get(transaction_id, {})
    revenus_items.append({'id': transaction_id, 'nom': row['Site'], 'montant': row['Montant'],
        'mois': mois_choisi.capitalize(), 'annee': annee_choisie, 'icon': '📈',
        'status': statut_info.get('statut', 'en_attente'), 'montant_avance': statut_info.get('montant_avance', 0),
        'av1': statut_info.get('av1', statut_info.get('montant_avance', 0) if statut_info.get('av2', 0) == 0 and statut_info.get('av3', 0) == 0 else 0),
        'av2': statut_info.get('av2', 0), 'av3': statut_info.get('av3', 0),
        'preuve_nom': statut_info.get('preuve_nom', None)})
        
charges_items = []
for _, row in charges_par_prestataire.iterrows():
    if row['Montant'] > 0:
        transaction_id = f"charge_{annee_choisie}_{mois_choisi}_{row['Prestataire'].replace(' ', '_')}"
        statut_info = status_data.get(transaction_id, {})
        charges_items.append({'id': transaction_id, 'nom': row['Prestataire'], 'montant': row['Montant'],
            'mois': mois_choisi.capitalize(), 'annee': annee_choisie, 'icon': '📉',
            'status': statut_info.get('statut', 'en_attente'), 'montant_avance': statut_info.get('montant_avance', 0),
            'av1': statut_info.get('av1', statut_info.get('montant_avance', 0) if statut_info.get('av2', 0) == 0 and statut_info.get('av3', 0) == 0 else 0),
            'av2': statut_info.get('av2', 0), 'av3': statut_info.get('av3', 0),
            'preuve_nom': statut_info.get('preuve_nom', None)})

partages_items = []
# Part Nogali  = 50% bénéfice Miamboo + 100% bénéfice Ringover
# Part AETECH  = 50% bénéfice Miamboo seulement
part_miamboo = synthese['benefice_miamboo'] * 0.5
part_ringover_nogali = synthese['benefice_ringover']  # déjà 100% Nogali
part_nogali_total = part_miamboo + part_ringover_nogali
part_aetech_total = part_miamboo

if part_nogali_total != 0 or part_aetech_total != 0:
    for partenaire, montant_part in [("Nogali", part_nogali_total), ("AETECH", part_aetech_total)]:
        if montant_part == 0:
            continue
        transaction_id = f"repartition_{annee_choisie}_{mois_choisi}_{partenaire}"
        statut_info = status_data.get(transaction_id, {})
        partages_items.append({'id': transaction_id, 'nom': f"Part {partenaire}", 'montant': montant_part,
            'mois': mois_choisi.capitalize(), 'annee': annee_choisie, 'icon': '🤝',
            'status': statut_info.get('statut', 'en_attente'), 'montant_avance': statut_info.get('montant_avance', 0),
            'av1': statut_info.get('av1', statut_info.get('montant_avance', 0) if statut_info.get('av2', 0) == 0 and statut_info.get('av3', 0) == 0 else 0),
            'av2': statut_info.get('av2', 0), 'av3': statut_info.get('av3', 0),
            'preuve_nom': statut_info.get('preuve_nom', None)})


with tab_mensuel:
    if not can_fin_mensuel:
        st.warning("⛔ Module non autorisé: Vue mensuelle.")
    # ── Charger les corrections et recalculer si nécessaire ──
    corrections = charger_corrections()
    rev_corrigee, chr_corrigee = appliquer_corrections(revenus_par_site, charges_par_prestataire, annee_choisie, mois_choisi, corrections)
    synthese_corrigee = calculer_synthese(revenus_miamboo, revenus_ringover, df_charges, annee_choisie, mois_choisi)
    # Override synthese totals si corrections existent
    cle_base = f"{annee_choisie}_{mois_choisi}"
    corrections_du_mois = {k: v for k, v in corrections.items() if f"_{cle_base}_" in k}
    has_corrections = len(corrections_du_mois) > 0

    st.header(f"💰 Indicateurs - {mois_choisi.capitalize()} {annee_choisie}")
    if has_corrections:
        st.warning(f"⚠️ {len(corrections_du_mois)} correction(s) manuelle(s) appliquée(s) ce mois-ci.")

    total_rev_corr = rev_corrigee['Montant'].sum() if not rev_corrigee.empty else synthese['revenus']
    total_chr_corr = chr_corrigee['Montant'].sum() if not chr_corrigee.empty else synthese['charges']
    benef_net_corr = total_rev_corr - total_chr_corr
    # Part Nogali = 50% Miamboo + 100% bénéfice Ringover
    part_nogali_corr = synthese['benefice_miamboo'] * 0.5 + synthese['benefice_ringover']
    part_aetech_corr = synthese['benefice_miamboo'] * 0.5

    col1, col2, col3, col4 = st.columns(4)
    with col1: st.markdown(f'<div class="kpi-card revenus"><div class="kpi-label">📈 REVENUS</div><div class="kpi-value">{total_rev_corr:.0f} €</div></div>', unsafe_allow_html=True)
    with col2: st.markdown(f'<div class="kpi-card charges"><div class="kpi-label">📉 CHARGES</div><div class="kpi-value">{total_chr_corr:.0f} €</div></div>', unsafe_allow_html=True)
    with col3: st.markdown(f'<div class="kpi-card benefice"><div class="kpi-label">💰 BÉNÉFICE NET</div><div class="kpi-value">{benef_net_corr:.0f} €</div></div>', unsafe_allow_html=True)
    with col4: st.markdown(f'<div class="kpi-card repartition"><div class="kpi-label">🤝 RÉPARTITION</div><div class="kpi-value" style="font-size: 1.15rem; line-height: 1.4;">Nogali: {part_nogali_corr:.0f} €<br>AETECH: {part_aetech_corr:.0f} €</div></div>', unsafe_allow_html=True)

    st.subheader("📋 Détail par activité")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Miamboo** (partagé 50/50)")
        st.write(f"Revenus : {synthese['revenus_miamboo']:.2f} €")
        st.write(f"Charges : {synthese['charges_miamboo']:.2f} €")
        st.write(f"Bénéfice : {synthese['benefice_miamboo']:.2f} €")
        st.write(f"→ Nogali (50%) : {synthese['benefice_miamboo'] * 0.5:.2f} €")
        st.write(f"→ AETECH (50%) : {synthese['benefice_miamboo'] * 0.5:.2f} €")
    with col_b:
        st.markdown("**Ringover** (100% Nogali)")
        st.write(f"Revenus : {synthese['revenus_ringover']:.2f} €")
        # ── Détail Ringover par agent ──
        detail_ringover = calculer_revenus_ringover_par_agent(revenus_ringover, annee_choisie, mois_choisi)
        if not detail_ringover.empty:
            for _, r in detail_ringover.iterrows():
                st.write(f"  ↳ {r['Agent']} : {r['Montant']:.2f} €")
        st.write(f"Charges : {synthese['charges_ringover']:.2f} €")
        st.write(f"Bénéfice : {synthese['benefice_ringover']:.2f} €")
        st.write(f"→ Nogali : {synthese['benefice_ringover']:.2f} €")

    # ── Tableaux avec marqueur de correction ──
    st.subheader(f"📋 Revenus par Site - {mois_choisi.capitalize()} {annee_choisie}")
    if not rev_corrigee.empty:
        def style_correction_rev(row):
            cle = f"rev_{cle_base}_{row['Site'].replace(' ','_')}"
            if cle in corrections:
                return ['background-color: rgba(255,193,7,0.2)'] * len(row)
            return [''] * len(row)
        st.dataframe(rev_corrigee.style.format({'Montant': '{:.2f} €'}).apply(style_correction_rev, axis=1), use_container_width=True, hide_index=True)

    st.subheader(f"📋 Charges par Prestataire - {mois_choisi.capitalize()} {annee_choisie}")
    if not chr_corrigee.empty:
        charges_aff = chr_corrigee[chr_corrigee['Montant'] > 0]
        if not charges_aff.empty:
            def style_correction_chr(row):
                cle = f"chr_{cle_base}_{row['Prestataire'].replace(' ','_')}"
                if cle in corrections:
                    return ['background-color: rgba(255,193,7,0.2)'] * len(row)
                return [''] * len(row)
            st.dataframe(charges_aff.style.format({'Montant': '{:.2f} €'}).apply(style_correction_chr, axis=1), use_container_width=True, hide_index=True)

    # ── PANNEAU D'ÉDITION MANUELLE ──────────────────────────────────────────
    st.divider()
    with st.expander("✏️ Mode Édition — Corriger les montants importés", expanded=False):
        st.caption("Les corrections sont sauvegardées localement et s'appliquent aux calculs. Les cellules corrigées apparaissent en jaune dans les tableaux.")

        ed_col1, ed_col2 = st.columns(2)

        with ed_col1:
            st.markdown("**📈 Corriger les Revenus**")
            # Récupérer tous les sites connus (API + corrections existantes)
            sites_connus = list(rev_corrigee['Site'].unique()) if not rev_corrigee.empty else []
            # Ajouter un site manuel
            nouveau_site = st.text_input("➕ Ajouter un site (si manquant dans l'API)", key=f"new_site_{annee_choisie}_{mois_choisi}", placeholder="ex: Site ABC")
            if nouveau_site and nouveau_site not in sites_connus:
                sites_connus.append(nouveau_site)

            rev_inputs = {}
            for site in sites_connus:
                cle_rev = f"rev_{cle_base}_{site.replace(' ','_')}"
                val_actuelle = corrections.get(cle_rev,
                    float(rev_corrigee.loc[rev_corrigee['Site']==site, 'Montant'].values[0]) if site in rev_corrigee['Site'].values else 0.0)
                rev_inputs[site] = st.number_input(
                    f"{site}",
                    min_value=0.0, value=float(val_actuelle), step=10.0, format="%.2f",
                    key=f"edit_rev_{annee_choisie}_{mois_choisi}_{site}"
                )

        with ed_col2:
            st.markdown("**📉 Corriger les Charges**")
            prestataires_connus = list(chr_corrigee['Prestataire'].unique()) if not chr_corrigee.empty else ['Inextrix','Ceffage','Coriolis','Contabo','Ringover']
            nouveau_prest = st.text_input("➕ Ajouter un prestataire (si manquant)", key=f"new_prest_{annee_choisie}_{mois_choisi}", placeholder="ex: Nouveau Prestataire")
            if nouveau_prest and nouveau_prest not in prestataires_connus:
                prestataires_connus.append(nouveau_prest)

            chr_inputs = {}
            for prest in prestataires_connus:
                cle_chr = f"chr_{cle_base}_{prest.replace(' ','_')}"
                val_actuelle = corrections.get(cle_chr,
                    float(chr_corrigee.loc[chr_corrigee['Prestataire']==prest, 'Montant'].values[0]) if prest in chr_corrigee['Prestataire'].values else 0.0)
                chr_inputs[prest] = st.number_input(
                    f"{prest}",
                    min_value=0.0, value=float(val_actuelle), step=10.0, format="%.2f",
                    key=f"edit_chr_{annee_choisie}_{mois_choisi}_{prest}"
                )

        save_col, reset_col = st.columns(2)
        with save_col:
            if st.button("💾 Enregistrer les corrections", type="primary", use_container_width=True, key=f"btn_save_corr_{annee_choisie}_{mois_choisi}"):
                # Supprimer anciennes corrections du mois
                corrections = {k: v for k, v in corrections.items() if f"_{cle_base}_" not in k}
                # Ajouter les nouvelles (seulement si différent de 0)
                for site, val in rev_inputs.items():
                    orig = float(rev_corrigee.loc[rev_corrigee['Site']==site, 'Montant'].values[0]) if site in rev_corrigee['Site'].values else 0.0
                    if val != orig or site not in rev_corrigee['Site'].values:
                        corrections[f"rev_{cle_base}_{site.replace(' ','_')}"] = val
                for prest, val in chr_inputs.items():
                    orig = float(chr_corrigee.loc[chr_corrigee['Prestataire']==prest, 'Montant'].values[0]) if prest in chr_corrigee['Prestataire'].values else 0.0
                    if val != orig or prest not in chr_corrigee['Prestataire'].values:
                        corrections[f"chr_{cle_base}_{prest.replace(' ','_')}"] = val
                sauvegarder_corrections(corrections)
                st.success("✅ Corrections sauvegardées ! La page va se rafraîchir.")
                st.rerun()
        with reset_col:
            if st.button("🗑️ Réinitialiser ce mois", use_container_width=True, key=f"btn_reset_corr_{annee_choisie}_{mois_choisi}"):
                corrections = {k: v for k, v in corrections.items() if f"_{cle_base}_" not in k}
                sauvegarder_corrections(corrections)
                st.success("Corrections du mois supprimées.")
                st.rerun()

    st.divider()
    st.subheader("📥 Export")
    if st.button("📊 Exporter au format Excel", use_container_width=True):
        try:
            with pd.ExcelWriter("rapport_nogali.xlsx") as writer:
                pd.DataFrame([synthese]).to_excel(writer, sheet_name="Synthèse", index=False)
                rev_corrigee.to_excel(writer, sheet_name="Revenus_par_Site", index=False)
                chr_corrigee.to_excel(writer, sheet_name="Charges_par_Prestataire", index=False)
            st.success("✅ Export réussi !")
            with open("rapport_nogali.xlsx", "rb") as f:
                st.download_button("📥 Télécharger Excel", f, "rapport_nogali.xlsx")
        except Exception as e:
            st.error(f"Erreur : {e}")

with tab_suivi:
    if not can_fin_suivi:
        st.warning("⛔ Module non autorisé: Suivi paiements.")
    st.header(f"💳 Suivi des Règlements - {mois_choisi.capitalize()} {annee_choisie}")
    status_data = charger_status()
    col_liste1, col_liste2, col_liste3 = st.columns(3)
    with col_liste1: afficher_liste_paiements(revenus_items, "📈 Revenus", "revenus")
    with col_liste2: afficher_liste_paiements(charges_items, "📉 Charges", "charges")
    with col_liste3: afficher_liste_paiements(partages_items, "🤝 Répartition Miamboo", "répartition")


with tab_dashboard:
    if not can_fin_dashboard:
        st.warning("⛔ Module non autorisé: Tableau de bord.")
    st.header("🌍 Tableau de Bord & Trésorerie")

    vue_type = st.radio("Mode d'analyse :", ["📅 Ce mois uniquement", "🌍 Toute l'année combinée"], horizontal=True)
    target_mois = [mois_choisi] if "mois" in vue_type else list(mois_avec_donnees)

    with st.spinner("Analyse des flux de trésorerie..."):
        all_items = []
        status_data = charger_status()

        for a in [annee_choisie]:
            for m in target_mois:
                if m == 'inconnu': continue
                rev_site = calculer_revenus_par_site(revenus_miamboo, a, m)
                chr_prest = calculer_charges_par_prestataire(df_charges, a, m)
                syn = calculer_synthese(revenus_miamboo, revenus_ringover, df_charges, a, m)

                for _, row in rev_site.iterrows():
                    if row['Montant'] > 0:
                        tid = f"revenu_{a}_{m}_{row['Site'].replace(' ', '_')}"
                        st_info = status_data.get(tid, {})
                        statut = st_info.get('statut', 'en_attente')
                        avance = st_info.get('montant_avance', 0)
                        reste = row['Montant'] if statut == 'en_attente' else (row['Montant'] - avance if statut == 'avance' else 0)
                        all_items.append({'Mois': m.capitalize(), 'Type': 'Revenus', 'Partenaire': row['Site'], 'Statut': statut, 'Total Attendu': row['Montant'], 'Avance': float(avance), 'Reste': float(reste)})

                for _, row in chr_prest.iterrows():
                    if row['Montant'] > 0:
                        tid = f"charge_{a}_{m}_{row['Prestataire'].replace(' ', '_')}"
                        st_info = status_data.get(tid, {})
                        statut = st_info.get('statut', 'en_attente')
                        avance = st_info.get('montant_avance', 0)
                        reste = row['Montant'] if statut == 'en_attente' else (row['Montant'] - avance if statut == 'avance' else 0)
                        all_items.append({'Mois': m.capitalize(), 'Type': 'Charges', 'Partenaire': row['Prestataire'], 'Statut': statut, 'Total Attendu': row['Montant'], 'Avance': float(avance), 'Reste': float(reste)})

                part_mia = syn['benefice_miamboo'] * 0.5
                part_ring = syn['benefice_ringover']
                parts_dashboard = [("Nogali", part_mia + part_ring), ("AETECH", part_mia)]
                for p, part in parts_dashboard:
                    if part == 0:
                        continue
                    tid = f"repartition_{a}_{m}_{p}"
                    st_info = status_data.get(tid, {})
                    statut = st_info.get('statut', 'en_attente')
                    avance = st_info.get('montant_avance', 0)
                    reste = part if statut == 'en_attente' else (part - avance if statut == 'avance' else 0)
                    all_items.append({'Mois': m.capitalize(), 'Type': 'Répartition', 'Partenaire': f"Part {p}", 'Statut': statut, 'Total Attendu': part, 'Avance': float(avance), 'Reste': float(reste)})

        if all_items:
            import plotly.graph_objects as go
            df_g = pd.DataFrame(all_items)

            # ── LIGNE 1 : 5 KPI ─────────────────────────────────────────────────
            total_rev  = df_g[df_g['Type'] == 'Revenus']['Total Attendu'].sum()
            total_chr  = df_g[df_g['Type'] == 'Charges']['Total Attendu'].sum()
            total_rep  = df_g[df_g['Type'] == 'Répartition']['Total Attendu'].sum()
            total_av   = df_g['Avance'].sum()
            benef_net  = total_rev - total_chr

            k1, k2, k3, k4, k5 = st.columns(5)
            with k1:
                st.markdown(f'<div class="kpi-card revenus"><div class="kpi-label">📈 REVENUS ATTENDUS</div><div class="kpi-value">{total_rev:,.0f} €</div></div>', unsafe_allow_html=True)
            with k2:
                st.markdown(f'<div class="kpi-card charges"><div class="kpi-label">📉 CHARGES OPÉ.</div><div class="kpi-value">{total_chr:,.0f} €</div></div>', unsafe_allow_html=True)
            with k3:
                st.markdown(f'<div class="kpi-card repartition"><div class="kpi-label">🤝 RÉPARTITION</div><div class="kpi-value">{total_rep:,.0f} €</div></div>', unsafe_allow_html=True)
            with k4:
                st.markdown(f'<div class="kpi-card" style="background:linear-gradient(135deg,#f7971e,#ffd200)"><div class="kpi-label">💰 AVANCES</div><div class="kpi-value">{total_av:,.0f} €</div></div>', unsafe_allow_html=True)
            with k5:
                coul = "linear-gradient(135deg,#11998e,#38ef7d)" if benef_net >= 0 else "linear-gradient(135deg,#eb3349,#f45c43)"
                st.markdown(f'<div class="kpi-card" style="background:{coul}"><div class="kpi-label">💎 BÉNÉFICE NET</div><div class="kpi-value">{benef_net:,.0f} €</div></div>', unsafe_allow_html=True)

            st.write("")

            # ── LIGNE 2 : 4 GRAPHIQUES ──────────────────────────────────────────
            g1, g2, g3, g4 = st.columns(4)

            with g1:
                df_ens = pd.DataFrame({'Cat': ['Revenus', 'Charges', 'Répartition'], 'Montant': [total_rev, total_chr, total_rep]})
                fig_ens = px.bar(df_ens, x='Montant', y='Cat', orientation='h', title="📊 Vue d'ensemble",
                    color='Cat', color_discrete_map={'Revenus': '#38ef7d', 'Charges': '#f45c43', 'Répartition': '#f093fb'}, text_auto='.0f')
                fig_ens.update_layout(showlegend=False, margin=dict(l=0,r=0,t=40,b=0), height=260, yaxis_title="")
                fig_ens.update_traces(textposition='outside')
                st.plotly_chart(fig_ens, use_container_width=True)

            with g2:
                ratio = (total_chr / total_rev * 100) if total_rev > 0 else 0
                fig_ratio = go.Figure(go.Pie(
                    values=[ratio, max(0, 100 - ratio)], labels=['Charges', 'Bénéfice'],
                    hole=0.62, marker_colors=['#f45c43', '#38ef7d'], textinfo='none'))
                fig_ratio.add_annotation(text=f"<b>{ratio:.0f}%</b>", x=0.5, y=0.5, font_size=26, showarrow=False)
                fig_ratio.update_layout(title="📉 % Dépenses/Revenus", showlegend=True, margin=dict(l=0,r=0,t=40,b=0), height=260)
                st.plotly_chart(fig_ratio, use_container_width=True)

            with g3:
                df_cd = df_g[df_g['Type'] == 'Charges'].groupby('Partenaire')['Total Attendu'].sum().reset_index()
                if not df_cd.empty:
                    fig_cd = go.Figure(go.Pie(values=df_cd['Total Attendu'], labels=df_cd['Partenaire'], hole=0.45, textinfo='label+percent'))
                    fig_cd.update_layout(title="💸 Répartition Charges", showlegend=False, margin=dict(l=0,r=0,t=40,b=0), height=260)
                    st.plotly_chart(fig_cd, use_container_width=True)

            with g4:
                df_prog = df_g.groupby('Type')[['Avance','Reste']].sum().reset_index()
                fig_prog = px.bar(df_prog, x='Type', y=['Avance', 'Reste'], title="📈 Progression Paiements",
                    barmode='stack', color_discrete_map={'Avance': '#ffd200', 'Reste': '#dc3545'}, text_auto='.0f')
                fig_prog.update_layout(showlegend=True, margin=dict(l=0,r=0,t=40,b=0), height=260, legend=dict(orientation='h', y=-0.3))
                st.plotly_chart(fig_prog, use_container_width=True)

            # ── LIGNE 3 : 3 TABLEAUX ────────────────────────────────────────────
            st.divider()
            st.markdown("### 📋 Détail par Catégorie")
            t1, t2, t3 = st.columns(3)

            def style_row_statut(row):
                """Colore toute la ligne selon le statut"""
                s = row.get('Statut', '')
                if s == 'paye':
                    return ['background-color: rgba(40,167,69,0.20)'] * len(row)
                elif s == 'avance':
                    return ['background-color: rgba(255,193,7,0.20)'] * len(row)
                elif s == 'en_attente':
                    return ['background-color: rgba(220,53,69,0.12)'] * len(row)
                else:  # ligne TOTAL
                    return ['font-weight:bold; border-top: 1px solid rgba(255,255,255,0.2)'] * len(row)

            def statut_label(s):
                if s == 'paye': return '✅ Payé'
                elif s == 'avance': return '💰 Avance'
                elif s == 'en_attente': return '⏳ En attente'
                return ''

            with t1:
                st.markdown('<div style="border-top:3px solid #38ef7d;border-radius:8px;padding:4px 8px;margin-bottom:6px"><b>📈 Revenus</b></div>', unsafe_allow_html=True)
                df_rev_base = df_g[df_g['Type'] == 'Revenus'].copy()
                # Statut dominant par partenaire (paye > avance > en_attente)
                def statut_dominant(statuts):
                    if 'paye' in statuts.values: return 'paye'
                    if 'avance' in statuts.values: return 'avance'
                    return 'en_attente'
                df_rt = df_rev_base.groupby('Partenaire').agg(
                    Attendu=('Total Attendu','sum'), Avance=('Avance','sum'), Reste=('Reste','sum'),
                    Statut=('Statut', statut_dominant)
                ).reset_index().rename(columns={'Partenaire':'Site'})
                df_rt['Statut'] = df_rt['Statut'].apply(statut_label)
                df_rt_total = pd.DataFrame([{'Site':'TOTAL','Attendu':df_rt['Attendu'].sum(),'Avance':df_rt['Avance'].sum(),'Reste':df_rt['Reste'].sum(),'Statut':''}])
                df_rt = pd.concat([df_rt, df_rt_total], ignore_index=True)
                fmt = {'Attendu':'{:,.0f} €','Avance':'{:,.0f} €','Reste':'{:,.0f} €'}
                st.dataframe(df_rt.style.format(fmt).apply(style_row_statut, axis=1), use_container_width=True, hide_index=True)

            with t2:
                st.markdown('<div style="border-top:3px solid #f45c43;border-radius:8px;padding:4px 8px;margin-bottom:6px"><b>📉 Charges</b></div>', unsafe_allow_html=True)
                df_chr_base = df_g[df_g['Type'] == 'Charges'].copy()
                df_ct = df_chr_base.groupby('Partenaire').agg(
                    Attendu=('Total Attendu','sum'), Avance=('Avance','sum'), Reste=('Reste','sum'),
                    Statut=('Statut', statut_dominant)
                ).reset_index().rename(columns={'Partenaire':'Prestataire'})
                df_ct['Statut'] = df_ct['Statut'].apply(statut_label)
                df_ct_total = pd.DataFrame([{'Prestataire':'TOTAL','Attendu':df_ct['Attendu'].sum(),'Avance':df_ct['Avance'].sum(),'Reste':df_ct['Reste'].sum(),'Statut':''}])
                df_ct = pd.concat([df_ct, df_ct_total], ignore_index=True)
                st.dataframe(df_ct.style.format(fmt).apply(style_row_statut, axis=1), use_container_width=True, hide_index=True)

            with t3:
                st.markdown('<div style="border-top:3px solid #f093fb;border-radius:8px;padding:4px 8px;margin-bottom:6px"><b>🤝 Répartition</b></div>', unsafe_allow_html=True)
                df_rep_base = df_g[df_g['Type'] == 'Répartition'].copy()
                df_rept = df_rep_base.groupby('Partenaire').agg(
                    Part=('Total Attendu','sum'), Avance=('Avance','sum'), Reste=('Reste','sum'),
                    Statut=('Statut', statut_dominant)
                ).reset_index().rename(columns={'Partenaire':'Associé'})
                df_rept['Statut'] = df_rept['Statut'].apply(statut_label)
                df_rept_total = pd.DataFrame([{'Associé':'TOTAL','Part':df_rept['Part'].sum(),'Avance':df_rept['Avance'].sum(),'Reste':df_rept['Reste'].sum(),'Statut':''}])
                df_rept = pd.concat([df_rept, df_rept_total], ignore_index=True)
                fmt2 = {'Part':'{:,.0f} €','Avance':'{:,.0f} €','Reste':'{:,.0f} €'}
                st.dataframe(df_rept.style.format(fmt2).apply(style_row_statut, axis=1), use_container_width=True, hide_index=True)

            # ── ÉVOLUTION ANNUELLE ───────────────────────────────────────────────
            if "année" in vue_type and len(target_mois) > 1:
                st.divider()
                st.markdown("### 📊 Évolution Mensuelle des Restes à Régler")
                df_evol = df_g[df_g['Reste'] > 0].groupby(['Mois', 'Type'])['Reste'].sum().reset_index()
                if not df_evol.empty:
                    mois_ord = [m for m in mois_ordre if m.capitalize() in df_evol['Mois'].unique()]
                    df_evol['Mois'] = pd.Categorical(df_evol['Mois'], categories=[m.capitalize() for m in mois_ord], ordered=True)
                    df_evol = df_evol.sort_values('Mois')
                    fig_evol = px.bar(df_evol, x='Mois', y='Reste', color='Type', barmode='group',
                        color_discrete_map={'Revenus':'#38ef7d','Charges':'#f45c43','Répartition':'#f093fb'}, text_auto='.0f')
                    fig_evol.update_layout(margin=dict(l=0,r=0,t=20,b=0), legend=dict(orientation='h', y=-0.2))
                    st.plotly_chart(fig_evol, use_container_width=True)
        else:
            st.info("Aucune donnée disponible pour la période sélectionnée.")
