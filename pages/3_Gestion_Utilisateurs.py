import streamlit as st
from datetime import datetime

from auth_shared import (
    charger_utilisateurs,
    sauvegarder_utilisateurs,
    hash_password,
    default_permissions,
)


def ensure_admin_access() -> bool:
    if "authentifie" not in st.session_state or not st.session_state.authentifie:
        st.switch_page("app.py")
        return False

    role = st.session_state.get("role", "user")
    if role != "super_admin":
        st.error("⛔ Accès réservé au Super Admin.")
        if st.button("Retour", use_container_width=True):
            st.switch_page("app.py")
        return False
    return True


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### Applications")
        st.page_link("app.py", label="Gestion Leads et SDA", icon="📋")
        st.page_link("pages/2_Nogali_Finance.py", label="Nogali Finance", icon="💰")
        st.page_link("pages/3_Gestion_Utilisateurs.py", label="Gestion Utilisateurs", icon="👥")
        st.markdown("---")
        st.markdown(f"👤 **{st.session_state.get('nom', '')}**")
        st.caption(f"@{st.session_state.get('identifiant', '')}")
        st.caption(f"Role: {st.session_state.get('role', 'user')}")
        st.markdown("---")
        if st.button("🚪 Se déconnecter", use_container_width=True):
            st.session_state.authentifie = False
            st.session_state.page = "login"
            st.session_state.identifiant = ""
            st.session_state.nom = ""
            st.session_state.role = "user"
            st.session_state.permissions = {}
            st.switch_page("app.py")


def main() -> None:
    st.set_page_config(page_title="Gestion Utilisateurs", page_icon="👥", layout="wide")
    if not ensure_admin_access():
        return

    render_sidebar()
    st.title("👥 Gestion des utilisateurs")
    st.markdown(
        """
        <style>
        .user-card {
            border-radius: 14px;
            padding: 14px 16px;
            margin-bottom: 12px;
            border: 1px solid color-mix(in srgb, var(--text-color, #111) 20%, transparent 80%);
            background: linear-gradient(
                145deg,
                color-mix(in srgb, var(--secondary-background-color, #f6f7fb) 92%, #7b61ff 8%),
                color-mix(in srgb, var(--secondary-background-color, #f6f7fb) 97%, #00bcd4 3%)
            );
            box-shadow: 0 4px 14px color-mix(in srgb, var(--text-color, #111) 12%, transparent 88%);
        }
        .user-card .line-1 {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
            gap: 8px;
            flex-wrap: wrap;
        }
        .user-card .name {
            font-size: 1rem;
            font-weight: 700;
            color: var(--text-color, #111);
        }
        .user-card .handle {
            color: color-mix(in srgb, var(--text-color, #111) 70%, transparent 30%);
            font-size: 0.9rem;
        }
        .user-card .badges {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .user-badge {
            padding: 4px 8px;
            border-radius: 999px;
            border: 1px solid color-mix(in srgb, var(--text-color, #111) 20%, transparent 80%);
            font-size: 0.8rem;
            color: var(--text-color, #111);
            background: color-mix(in srgb, var(--background-color, #fff) 85%, #7b61ff 15%);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    users = charger_utilisateurs()
    tab_accounts, tab_roles, tab_security = st.tabs(["👤 Comptes", "🛡️ Rôles & Droits", "🔐 Sécurité"])

    with tab_accounts:
        st.subheader("Utilisateurs existants")
        for identifiant, infos in users.items():
            role = infos.get("role", "user")
            perms = infos.get("permissions", default_permissions(role))
            if role == "super_admin":
                role_label = "👑 Super Admin"
            elif role == "admin":
                role_label = "🛡️ Admin"
            else:
                role_label = "👤 User"

            leads_label = "✅ Leads" if perms.get("access_admin_leads_pro", False) else "❌ Leads"
            finance_label = "✅ Finance" if perms.get("access_nogali_finance", False) else "❌ Finance"

            row1, row2 = st.columns([6, 1])
            with row1:
                st.markdown(
                    f"""
                    <div class="user-card">
                        <div class="line-1">
                            <div>
                                <div class="name">{infos.get('nom', identifiant)}</div>
                                <div class="handle">@{identifiant}</div>
                            </div>
                            <div class="badges">
                                <span class="user-badge">{role_label}</span>
                                <span class="user-badge">{leads_label}</span>
                                <span class="user-badge">{finance_label}</span>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with row2:
                if identifiant not in ["admin", "superadmin"]:
                    if st.button("🗑️", key=f"del_pg_{identifiant}", use_container_width=True):
                        del users[identifiant]
                        sauvegarder_utilisateurs(users)
                        st.success(f"Utilisateur @{identifiant} supprimé.")
                        st.rerun()

        with st.expander("➕ Créer un utilisateur", expanded=False):
            new_id = st.text_input("Identifiant", key="new_user_id_pg")
            new_name = st.text_input("Nom", key="new_user_name_pg")
            new_pwd = st.text_input("Mot de passe", type="password", key="new_user_pwd_pg")
            new_role = st.selectbox("Rôle", ["user", "admin", "super_admin"], key="new_user_role_pg")
            if st.button("Créer l'utilisateur", use_container_width=True, key="create_user_pg"):
                if not new_id or not new_name or not new_pwd:
                    st.warning("Tous les champs sont requis.")
                elif new_id in users:
                    st.error("Cet identifiant existe déjà.")
                elif len(new_pwd) < 6:
                    st.warning("Mot de passe trop court (min 6).")
                else:
                    users[new_id] = {
                        "nom": new_name,
                        "mot_de_passe": hash_password(new_pwd),
                        "role": new_role,
                        "permissions": default_permissions(new_role),
                        "date_creation": datetime.now().isoformat(),
                    }
                    sauvegarder_utilisateurs(users)
                    st.success(f"Utilisateur @{new_id} créé.")
                    st.rerun()

        with st.expander("✏️ Éditer un utilisateur", expanded=False):
            edit_user = st.selectbox("Utilisateur à éditer", list(users.keys()), key="edit_user_select_pg")
            edit_data = users[edit_user]

            edit_name = st.text_input(
                "Nom complet",
                value=edit_data.get("nom", ""),
                key=f"edit_user_name_{edit_user}",
            )
            edit_identifiant = st.text_input(
                "Identifiant",
                value=edit_user,
                key=f"edit_user_id_{edit_user}",
                help="Changer l'identifiant déplacera le compte sous la nouvelle clé.",
            )

            if st.button("💾 Enregistrer les modifications", use_container_width=True, key="save_user_edit_pg"):
                new_id_value = edit_identifiant.strip()
                new_name_value = edit_name.strip()

                if not new_name_value or not new_id_value:
                    st.warning("Nom et identifiant sont requis.")
                elif edit_user in ["admin", "superadmin"] and new_id_value != edit_user:
                    st.error("Les identifiants des comptes système ne peuvent pas être modifiés.")
                elif new_id_value != edit_user and new_id_value in users:
                    st.error("Cet identifiant existe déjà.")
                else:
                    # Mise à jour du nom
                    users[edit_user]["nom"] = new_name_value

                    # Renommage de la clé utilisateur si besoin
                    if new_id_value != edit_user:
                        users[new_id_value] = users.pop(edit_user)

                    sauvegarder_utilisateurs(users)
                    st.success(f"Utilisateur mis à jour: @{new_id_value}")
                    st.rerun()

    with tab_roles:
        st.subheader("Rôles & droits applicatifs")
        selected_user = st.selectbox("Utilisateur", list(users.keys()), key="user_manage_select")
        selected = users[selected_user]
        current_role = selected.get("role", "user")
        current_permissions = selected.get("permissions", default_permissions(current_role))

        new_role = st.selectbox(
            "Rôle",
            ["user", "admin", "super_admin"],
            index=["user", "admin", "super_admin"].index(current_role) if current_role in ["user", "admin", "super_admin"] else 0,
            key="user_manage_role",
        )
        if st.button("💾 Enregistrer le rôle", use_container_width=True, key="save_role_on_page"):
            if selected_user == "superadmin" and new_role != "super_admin":
                st.error("Le compte superadmin doit rester super_admin.")
            elif selected_user == "admin" and new_role == "user":
                st.error("Le compte admin ne peut pas être rétrogradé en user.")
            else:
                users[selected_user]["role"] = new_role
                merged = default_permissions(new_role)
                if isinstance(current_permissions, dict):
                    merged.update(current_permissions)
                users[selected_user]["permissions"] = merged
                sauvegarder_utilisateurs(users)
                st.success(f"Rôle mis à jour pour @{selected_user}.")
                st.rerun()

        st.markdown("---")
        st.markdown("### Accès applications")
        can_access_leads = st.checkbox(
            "Accès application Gestion Leads et SDA",
            value=bool(current_permissions.get("access_admin_leads_pro", current_role in ["admin", "super_admin"])),
            key="pg_perm_leads",
        )
        can_access_finance = st.checkbox(
            "Accès application Nogali Finance",
            value=bool(current_permissions.get("access_nogali_finance", current_role in ["admin", "super_admin"])),
            key="pg_perm_finance",
        )

        st.markdown("### Modules Finance")
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            perm_fin_dashboard = st.checkbox(
                "Finance - Tableau de bord",
                value=bool(current_permissions.get("access_fin_dashboard", True)),
                key="pg_perm_fin_dashboard",
            )
        with fc2:
            perm_fin_mensuel = st.checkbox(
                "Finance - Vue mensuelle",
                value=bool(current_permissions.get("access_fin_mensuel", True)),
                key="pg_perm_fin_mensuel",
            )
        with fc3:
            perm_fin_suivi = st.checkbox(
                "Finance - Suivi paiements",
                value=bool(current_permissions.get("access_fin_suivi", True)),
                key="pg_perm_fin_suivi",
            )

        st.markdown("### Modules Gestion Leads et SDA")
        mc1, mc2 = st.columns(2)
        with mc1:
            perm_import = st.checkbox("Module IMPORT", value=bool(current_permissions.get("access_module_import", False)), key="pg_perm_import")
            perm_telephone = st.checkbox("Module TÉLÉPHONE", value=bool(current_permissions.get("access_module_telephone", False)), key="pg_perm_tel")
            perm_doublons = st.checkbox("Module DOUBLONS", value=bool(current_permissions.get("access_module_doublons", False)), key="pg_perm_dbl")
            perm_filtre = st.checkbox("Module FILTRE", value=bool(current_permissions.get("access_module_filtre", False)), key="pg_perm_filtre")
        with mc2:
            perm_export = st.checkbox("Module EXPORT", value=bool(current_permissions.get("access_module_export", False)), key="pg_perm_export")
            perm_verif_sda = st.checkbox("Module VÉRIF SDA", value=bool(current_permissions.get("access_module_verif_sda", False)), key="pg_perm_vsda")
            perm_alertes = st.checkbox("Module ALERTES", value=bool(current_permissions.get("access_module_alertes", False)), key="pg_perm_alertes")
            perm_base_sda = st.checkbox("Module BASE SDA", value=bool(current_permissions.get("access_module_base_sda", False)), key="pg_perm_bsda")

        if st.button("💾 Enregistrer les privilèges", use_container_width=True, key="save_all_permissions_on_page"):
            users[selected_user]["permissions"] = {
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
            sauvegarder_utilisateurs(users)
            st.success(f"Privilèges mis à jour pour @{selected_user}.")
            st.rerun()

    with tab_security:
        st.subheader("Sécurité des comptes")
        selected_user_pwd = st.selectbox("Utilisateur", list(users.keys()), key="user_manage_select_pwd")
        pwd1 = st.text_input("Nouveau mot de passe", type="password", key="user_manage_pwd1")
        pwd2 = st.text_input("Confirmer mot de passe", type="password", key="user_manage_pwd2")
        if st.button("🔑 Réinitialiser le mot de passe", use_container_width=True, key="save_pwd_on_page"):
            if not pwd1 or not pwd2:
                st.warning("Veuillez remplir les deux champs.")
            elif pwd1 != pwd2:
                st.error("Les mots de passe ne correspondent pas.")
            elif len(pwd1) < 6:
                st.warning("Le mot de passe doit contenir au moins 6 caractères.")
            else:
                users[selected_user_pwd]["mot_de_passe"] = hash_password(pwd1)
                users[selected_user_pwd]["date_modification"] = datetime.now().isoformat()
                sauvegarder_utilisateurs(users)
                st.success(f"Mot de passe mis à jour pour @{selected_user_pwd}.")
                st.rerun()


main()
