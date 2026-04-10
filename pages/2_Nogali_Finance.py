import os
import runpy
from pathlib import Path

import streamlit as st
from auth_shared import (
    PERMISSION_FINANCE,
    PERMISSION_LEADS,
    has_permission,
)


NOGALI_FINANCE_APP = Path(
    os.getenv(
        "NOGALI_FINANCE_APP_PATH",
        str(Path(__file__).resolve().parents[1] / "integrations" / "nogali_finance" / "app.py"),
    )
)


def ensure_finance_auth() -> bool:
    if "authentifie" not in st.session_state:
        st.session_state.authentifie = False
    if "role" not in st.session_state:
        st.session_state.role = "user"
    if "permissions" not in st.session_state:
        st.session_state.permissions = {}
    if "identifiant" not in st.session_state:
        st.session_state.identifiant = ""
    if "nom" not in st.session_state:
        st.session_state.nom = ""

    if not st.session_state.authentifie:
        st.switch_page("app.py")
        return False

    user_ctx = {
        "role": st.session_state.get("role", "user"),
        "permissions": st.session_state.get("permissions", {}),
    }
    can_leads = has_permission(user_ctx, PERMISSION_LEADS)
    can_finance = has_permission(user_ctx, PERMISSION_FINANCE)

    st.markdown(
        "<style>[data-testid='stSidebarNav']{display:none !important;}</style>",
        unsafe_allow_html=True,
    )
    with st.sidebar:
        st.markdown("### Applications")
        if can_leads:
            st.page_link("app.py", label="Gestion Leads et SDA", icon="📋")
        if can_finance:
            st.page_link("pages/2_Nogali_Finance.py", label="Nogali Finance", icon="💰")
        if st.session_state.get("role") == "super_admin":
            st.page_link("pages/3_Gestion_Utilisateurs.py", label="Gestion Utilisateurs", icon="👥")
        st.markdown("---")
        if st.button("🚪 Se déconnecter", use_container_width=True):
            st.session_state.authentifie = False
            st.session_state.page = "login"
            st.session_state.identifiant = ""
            st.session_state.nom = ""
            st.session_state.role = "user"
            st.session_state.permissions = {}
            st.switch_page("app.py")

    if not has_permission(
        user_ctx,
        PERMISSION_FINANCE,
    ):
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"],
            [data-testid="stSidebarNav"] { display: none !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.error("⛔ Vous n'avez pas l'autorisation d'accéder à Nogali Finance.")
        user_ctx = {
            "role": st.session_state.get("role", "user"),
            "permissions": st.session_state.get("permissions", {}),
        }
        if has_permission(user_ctx, PERMISSION_LEADS):
            st.page_link("app.py", label="Aller vers Admin Leads Pro", icon="📋")
        if st.button("Se déconnecter", use_container_width=True):
            st.session_state.authentifie = False
            st.session_state.page = "login"
            st.session_state.identifiant = ""
            st.session_state.nom = ""
            st.session_state.role = "user"
            st.session_state.permissions = {}
            st.rerun()
        return False

    return True


def run_finance_page() -> None:
    if not ensure_finance_auth():
        return

    role = st.session_state.get("role", "user")
    permissions = st.session_state.get("permissions", {})
    is_admin_like = role in ["admin", "super_admin"]
    if not is_admin_like:
        required_finance_modules = {
            "Tableau de bord": bool(permissions.get("access_fin_dashboard", True)),
            "Vue mensuelle": bool(permissions.get("access_fin_mensuel", True)),
            "Suivi paiements": bool(permissions.get("access_fin_suivi", True)),
        }
        denied = [name for name, allowed in required_finance_modules.items() if not allowed]
        if denied:
            st.error("⛔ Verrouillage strict activé: accès Nogali Finance refusé.")
            st.warning(
                "Modules refusés: " + ", ".join(denied) +
                ". Activez tous les modules Finance pour autoriser l'accès."
            )
            if st.button("Retour Gestion Leads et SDA", use_container_width=True):
                st.switch_page("app.py")
            return

    if not NOGALI_FINANCE_APP.exists():
        st.error(f"Le fichier finance est introuvable : {NOGALI_FINANCE_APP}")
        st.info(
            "Definis la variable d'environnement NOGALI_FINANCE_APP_PATH "
            "si le projet est dans un autre dossier."
        )
        return

    previous_cwd = Path.cwd()
    previous_set_page_config = st.set_page_config

    # Evite un conflit si la page finance rappelle set_page_config.
    st.set_page_config = lambda *args, **kwargs: None

    try:
        os.chdir(NOGALI_FINANCE_APP.parent)
        runpy.run_path(str(NOGALI_FINANCE_APP), run_name="__main__")
    finally:
        os.chdir(previous_cwd)
        st.set_page_config = previous_set_page_config


run_finance_page()
