import hashlib
import json
from pathlib import Path
from typing import Dict, Tuple, Any


USERS_FILE = Path(__file__).resolve().parent / "utilisateurs.json"

PERMISSION_LEADS = "access_admin_leads_pro"
PERMISSION_FINANCE = "access_nogali_finance"
PERMISSION_IMPORT = "access_module_import"
PERMISSION_TELEPHONE = "access_module_telephone"
PERMISSION_DOUBLONS = "access_module_doublons"
PERMISSION_FILTRE = "access_module_filtre"
PERMISSION_EXPORT = "access_module_export"
PERMISSION_VERIF_SDA = "access_module_verif_sda"
PERMISSION_ALERTES = "access_module_alertes"
PERMISSION_BASE_SDA = "access_module_base_sda"
PERMISSION_FIN_DASHBOARD = "access_fin_dashboard"
PERMISSION_FIN_MENSUEL = "access_fin_mensuel"
PERMISSION_FIN_SUIVI = "access_fin_suivi"


def hash_password(mot_de_passe: str) -> str:
    return hashlib.sha256(mot_de_passe.encode()).hexdigest()


def default_permissions(role: str) -> Dict[str, bool]:
    if role in ("admin", "super_admin"):
        return {
            PERMISSION_LEADS: True,
            PERMISSION_FINANCE: True,
            PERMISSION_IMPORT: True,
            PERMISSION_TELEPHONE: True,
            PERMISSION_DOUBLONS: True,
            PERMISSION_FILTRE: True,
            PERMISSION_EXPORT: True,
            PERMISSION_VERIF_SDA: True,
            PERMISSION_ALERTES: True,
            PERMISSION_BASE_SDA: True,
            PERMISSION_FIN_DASHBOARD: True,
            PERMISSION_FIN_MENSUEL: True,
            PERMISSION_FIN_SUIVI: True,
        }
    return {
        PERMISSION_LEADS: True,
        PERMISSION_FINANCE: False,
        PERMISSION_IMPORT: True,
        PERMISSION_TELEPHONE: True,
        PERMISSION_DOUBLONS: True,
        PERMISSION_FILTRE: True,
        PERMISSION_EXPORT: True,
        PERMISSION_VERIF_SDA: False,
        PERMISSION_ALERTES: False,
        PERMISSION_BASE_SDA: False,
        PERMISSION_FIN_DASHBOARD: True,
        PERMISSION_FIN_MENSUEL: True,
        PERMISSION_FIN_SUIVI: True,
    }


def _normalize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    role = user.get("role", "user")
    perms = user.get("permissions")
    if not isinstance(perms, dict):
        perms = {}

    defaults = default_permissions(role)
    for key, value in defaults.items():
        if key not in perms:
            perms[key] = value

    user["permissions"] = perms
    return user


def charger_utilisateurs() -> Dict[str, Dict[str, Any]]:
    if USERS_FILE.exists():
        try:
            with USERS_FILE.open("r", encoding="utf-8") as f:
                users = json.load(f)
        except Exception:
            return {}
    else:
        return {}

    if not isinstance(users, dict):
        return {}

    changed = False
    for identifiant, info in list(users.items()):
        normalized = _normalize_user(info if isinstance(info, dict) else {})
        if normalized != info:
            users[identifiant] = normalized
            changed = True

    if changed:
        sauvegarder_utilisateurs(users)
    return users


def sauvegarder_utilisateurs(utilisateurs: Dict[str, Dict[str, Any]]) -> None:
    with USERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(utilisateurs, f, indent=2, ensure_ascii=False)


def creer_utilisateur_defaut() -> Dict[str, Dict[str, Any]]:
    from datetime import datetime

    utilisateurs = charger_utilisateurs()
    if not utilisateurs:
        utilisateurs["admin"] = {
            "nom": "Administrateur",
            "mot_de_passe": hash_password("admin123"),
            "role": "admin",
            "permissions": default_permissions("admin"),
            "date_creation": datetime.now().isoformat(),
        }
        sauvegarder_utilisateurs(utilisateurs)
    return utilisateurs


def authentifier(identifiant: str, mot_de_passe: str) -> Tuple[bool, Dict[str, Any] | None]:
    utilisateurs = charger_utilisateurs()
    user = utilisateurs.get(identifiant)
    if not user:
        return False, None

    if user.get("mot_de_passe") == hash_password(mot_de_passe):
        return True, _normalize_user(user)
    return False, None


def has_permission(user_info: Dict[str, Any], permission_key: str) -> bool:
    perms = user_info.get("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
    if user_info.get("role") in ("admin", "super_admin"):
        return True
    return bool(perms.get(permission_key, False))
