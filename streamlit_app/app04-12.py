import matplotlib.pyplot as plt
import os
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from openai import OpenAI
import warnings
warnings.filterwarnings("ignore")
st.set_page_config(page_title="Assistant IA & Santé", layout="wide")
# ---- hide streamlit top bar ---
st.markdown("""
    <style>
        header.stAppHeader {display: none !important;}
        div.block-container {
            padding-top: 0rem !important;
            margin-top: 0rem !important;
        }
    </style>
""", unsafe_allow_html=True)
# --------------------------
# DATABASE CONNECTION
# --------------------------
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")
DB_HOST = os.getenv("POSTGRES_HOST", "db")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
engine = create_engine(
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
# --------------------------
# LOAD USER FROM DB
# --------------------------
def load_user(username):
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT username, password, role
            FROM users WHERE username = :u
        """), {"u": username}).fetchone()
        return row
# --------------------------
# SESSION STATE INIT
# --------------------------
for key, default in {
    "page": "selection",
    "selected_domain": None,
    "authenticated": False,
    "username": None,
    "role": None,
    "lang": "Français"
}.items():
    st.session_state.setdefault(key, default)

# --------------------------
######## LOGIN PAGE ####################
#---------------------------

def login_page():

    # --- Ligne contenant les 2 logos : Gauche et Droite ---
    col_left, col_center, col_right = st.columns([1, 5, 1])

    with col_left:
        st.image("DSP.png", width=110)
    with col_center:
        pass
    with col_right:
        st.image("IEF2I.png", width=110)

    # --- Styles CSS ---
    st.markdown("""
        <style>
            .login-container {
                max-width: 400px;
                margin: 5px auto;
                padding: 40px 30px;
                background: rgba(0,0,0,0.75);
                border-radius: 18px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.6);
                color: white;
                text-align: center;
                font-family: 'Poppins', sans-serif;
            }
            .login-title {
                font-size: 30px;
                font-weight: 800;
                margin-bottom: 10px;
            }
        </style>
    """, unsafe_allow_html=True)

    # --- Bloc de connexion ---
    st.markdown("""
        <div class="login-container">
            <div class="login-title">🔐 Accès sécurisé</div>
            Merci de vous connecter pour accéder à l'assistant IA & Santé.
        </div>
    """, unsafe_allow_html=True)

    # ============================
    # FORMULAIRE
    # ============================
    with st.form("login_form"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")

        login_clicked = st.form_submit_button("Se connecter")

    # TRAITEMENT DU LOGIN
    if login_clicked:
        row = load_user(username)
        if not row:
            st.error("Utilisateur inconnu.")
        else:
            db_user, db_pwd, db_role = row
            if password == db_pwd:
                st.session_state.authenticated = True
                st.session_state.username = db_user
                st.session_state.role = db_role
                st.session_state.page = "selection"
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")

    # ================================
    # MOT DE PASSE OUBLIÉ (VIEWERS)
    # ================================
    user_role = None
    try:
        if username.strip() != "":
            row_tmp = load_user(username)
            if row_tmp:
                user_role = row_tmp[2]  # role
    except:
        pass

    if user_role == "viewer":
        if st.button("🔑 Mot de passe oublié ?"):
            st.session_state.page = "reset_request"
            st.session_state.tmp_username = username
            st.rerun()



########################################
# PAGE RESET REQUEST
########################################
def page_reset_request():
    st.markdown("## 🔑 Réinitialisation du mot de passe")

    username = st.text_input("Identifiant", value=st.session_state.get("tmp_username", ""))
    email = st.text_input("Email")

    if st.button("Réinitialiser"):
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT email FROM users WHERE username = :u"),
                {"u": username}
            ).fetchone()

        if row and row[0] == email:
            st.session_state.reset_user = username
            st.session_state.page = "reset_password"
            st.rerun()
        else:
            st.error("❌ Identifiant ou email incorrect.")

#######

import re

def is_valid_password(pwd):
    # Doit contenir au moins une majuscule et un caractère spécial
    has_upper = re.search(r"[A-Z]", pwd) is not None
    has_special = re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=/]", pwd) is not None
    return has_upper and has_special


def page_reset_password():
    st.markdown("## 🔒 Définir un nouveau mot de passe")

    if "reset_user" not in st.session_state:
        st.error("Erreur : aucune demande en cours.")
        return

    # --------------------------------------------------------------------
    # AVANT MODIFICATION → afficher formulaire
    # --------------------------------------------------------------------
    if "password_changed" not in st.session_state:

        new_pwd = st.text_input("Nouveau mot de passe", type="password")
        st.markdown(
            "<span style='font-size:13px;color:#888;'>🔒 Le mot de passe doit contenir "
            "au moins <b>une majuscule</b> et <b>un caractère spécial</b>.</span>",
            unsafe_allow_html=True
        )

        confirm_pwd = st.text_input("Confirmer le mot de passe", type="password")
        st.markdown(
            "<span style='font-size:13px;color:#888;'>🔒 Entrez le même mot de passe pour confirmation.</span>",
            unsafe_allow_html=True
        )

        # --- BOUTON ---
        if st.button("Modifier le mot de passe"):

            # Vérifier correspondance
            if new_pwd != confirm_pwd:
                st.error("❌ Les mots de passe ne correspondent pas.")
                return

            # Vérifier règles de sécurité
            if not is_valid_password(new_pwd):
                st.error("❌ Le mot de passe doit contenir AU MOINS une majuscule et un caractère spécial.")
                return

            # Mise à jour dans la base
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE users SET password = :p WHERE username = :u"),
                    {"p": new_pwd, "u": st.session_state.reset_user}
                )

            # Marqueur pour afficher page succès
            st.session_state.password_changed = True
            st.rerun()

    # --------------------------------------------------------------------
    # APRÈS MODIFICATION → message + bouton retour
    # --------------------------------------------------------------------
    else:
        st.success("✅ Mot de passe modifié avec succès !")

        if st.button("🔙 Revenir à la page de connexion"):
            st.session_state.pop("reset_user", None)
            st.session_state.pop("password_changed", None)
            st.session_state.page = "login"
            st.session_state.authenticated = False
            st.rerun()

########################################
# ROUTING — RESET REQUEST
########################################
if st.session_state.page == "reset_request":
    page_reset_request()
    st.stop()


########################################
# ROUTING — RESET PASSWORD
########################################
if st.session_state.page == "reset_password":
    page_reset_password()
    st.stop()



########################################
# BLOCK LOGIN
########################################
if not st.session_state.authenticated:
    login_page()
    st.stop()

###########################
# --------------------------
# PAGE 1 — DOMAIN SELECTION
# --------------------------
if st.session_state.page == "selection":

    # DESIGN ORIGINAL 100% CONSERVÉ
    st.markdown("""
    <style>
        @keyframes gradientMove {
            0% {background-position: 0% 50%;}
            50% {background-position: 100% 50%;}
            100% {background-position: 0% 50%;}
        }
        .stApp {
            background: linear-gradient(-45deg, #000428, #004e92, #00e6ac, #001f3f);
            background-size: 400% 400%;
            animation: gradientMove 12s ease infinite;
            color: white;
            font-family: 'Poppins', sans-serif;
        }
        .title {
            font-size:46px; font-weight:900;
            text-align:center; color:white; margin-top:20px;
            text-shadow:0px 0px 15px rgba(0,230,172,0.9);
        }
        .subtitle {
            font-size:22px; color:#e0e0e0;
            text-align:center; margin-bottom:50px;
            font-weight:400;
        }

        /* Apparence des 4 boutons */
        .stButton > button {
            width:260px !important;
            height:260px !important;
            background:white !important;
            border-radius:25px !important;
            box-shadow:0 4px 20px rgba(0,0,0,0.35) !important;
            font-size:32px !important;
            font-weight:900 !important;
            text-decoration:underline !important;
            color:#001f3f !important;
            border:none !important;
        }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("<div class='title'>Assistant IA & Santé</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle'>Choisissez votre domaine</div>", unsafe_allow_html=True)

    # ======================
    # === BOUTONS ALIGNÉS ===
    # ======================

    if st.session_state.role == "admin":

        # 4 colonnes alignées
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

        with col1:
            if st.button("Intelligence\nArtificielle"):
                st.session_state.selected_domain = "Intelligence Artificielle"
                st.session_state.page = "main"
                st.rerun()

        with col2:
            if st.button("Santé"):
                st.session_state.selected_domain = "Santé"
                st.session_state.page = "main"
                st.rerun()

        with col3:
            if st.button("📊 Stats"):
                st.session_state.page = "stats"
                st.rerun()

        with col4:
            if st.button("⚙️ Paramétrage"):
                st.session_state.page = "settings"
                st.rerun()

    else:
        # VIEWER → deux boutons centrés comme avant
        col_empty1, col1, col2, col_empty2 = st.columns([1.5, 1, 1, 1.5])

        with col1:
            if st.button("Intelligence\nArtificielle"):
                st.session_state.selected_domain = "Intelligence Artificielle"
                st.session_state.page = "main"
                st.rerun()

        with col2:
            if st.button("Santé"):
                st.session_state.selected_domain = "Santé"
                st.session_state.page = "main"
                st.rerun()

    st.stop()


 #################################

def page_settings():

    st.markdown("""
    <style>

        .stApp {
            background-color:#001f3f !important;
        }

        h1, h2, h3, label, p {
            color:white !important;
        }

        .blue-bar {
            height: 6px;
            width: 100%;
            background: linear-gradient(90deg, #0f172a, #1e3a8a, #0ea5e9);
            border-radius: 8px;
            margin: 25px 0;
        }

        div[data-testid="stButton"] > button {
            background:white !important;
            color:#001f3f !important;
            font-weight:700 !important;
            border-radius:8px !important;
            border:1px solid #ccc !important;
        }
        div[data-testid="stButton"] > button * {
            color:#001f3f !important;
        }

        .stSelectbox [data-baseweb="select"],
        .stSelectbox ul[role="listbox"],
        .stSelectbox div[role="listbox"],
        .stSelectbox li,
        .stSelectbox div[role="option"],
        .stSelectbox li[data-baseweb="menu-item"] {
            background:white !important;
            color:black !important;
        }

        .stSelectbox li:hover {
            background:#e6e6e6 !important;
            color:black !important;
        }

        .stSelectbox svg {
            fill:#001f3f !important;
        }

        .stDataFrame div[role="menu"],
        .stDataFrame [data-baseweb="popover"] {
            background:white !important;
            color:black !important;
        }

        .stDataFrame div[role="menuitem"],
        .stDataFrame div[role="menu"] * {
            color:black !important;
        }

        .stDataFrame div[role="menuitem"]:hover {
            background:#e6e6e6 !important;
            color:black !important;
        }


        [data-testid="stElementToolbar"] {
            color: black !important;
        }

        [data-testid="stElementToolbar"] svg {
            fill: black !important;
            color: black !important;
        }

        [data-testid="stElementToolbar"] button:hover {
            background: #e6e6e6 !important;
        }

        div[data-baseweb="tooltip"] {
            background:white !important;
            color:black !important;
            border:1px solid #ccc !important;
        }

        div[data-baseweb="tooltip"] * {
            color:black !important;
            fill:black !important;
        }

        input[type="text"], input[type="password"] {
            background:white !important;
            color:black !important;
        }

    </style>
    """, unsafe_allow_html=True)

    # ---- TITRE ----
    st.markdown("<h1 style='text-align:center;'>⚙️ Paramétrage des utilisateurs</h1>", unsafe_allow_html=True)
    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ---- RETOUR ----
    if st.button("⬅ Retour"):
        st.session_state.page = "selection"
        st.rerun()

    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ---- CHARGER UTILISATEURS ----
    with engine.begin() as conn:
        users = pd.read_sql("SELECT id, username, password, role, email FROM users ORDER BY id", conn)

    # ============================
    #  👥 LISTE UTILISATEURS
    # ============================
    st.markdown("### 👥 Liste des utilisateurs")
    st.dataframe(users, use_container_width=True, hide_index=True)
    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ============================
    #  ➕ AJOUTER UN UTILISATEUR
    # ============================
    st.markdown("### ➕ Ajouter un utilisateur")

    col1, col2, col3 = st.columns(3)
    with col1:
        new_user = st.text_input("Nom d'utilisateur")

    with col2:
        new_password = st.text_input("Mot de passe", type="password")

    with col3:
        new_role = st.selectbox("Rôle", ["viewer", "admin"], key="add_role")

    add_btn = st.button("Ajouter l'utilisateur")

    if add_btn:
        if new_user.strip() == "" or new_password.strip() == "":
            st.session_state["add_msg"] = ("error", "⚠️ Veuillez remplir tous les champs.")
        else:
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO users (username, password, role) VALUES (:u, :p, :r)"),
                        {"u": new_user, "p": new_password, "r": new_role}
                    )
                st.session_state["add_msg"] = ("success", f"Utilisateur **{new_user}** ajouté.")
            except Exception as e:
                st.session_state["add_msg"] = ("error", f"Erreur SQL : {e}")

        st.rerun()

    # ⭐ AFFICHER LE MESSAGE JUSTE ICI
    if "add_msg" in st.session_state:
        msg_type, msg = st.session_state["add_msg"]
        if msg_type == "success":
            st.success(msg)
        else:
            st.error(msg)
        del st.session_state["add_msg"]

    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ============================
    #  🗑️ SUPPRIMER UN UTILISATEUR
    # ============================
    st.markdown("### 🗑️ Supprimer un utilisateur")

    user_list = list(users["username"])
    user_to_delete = st.selectbox("Sélectionner l'utilisateur", user_list, key="delete_user")

    del_btn = st.button("Supprimer")

    if del_btn:
        try:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM users WHERE username = :u"),
                             {"u": user_to_delete})
            st.session_state["delete_msg"] = ("success", f"Utilisateur **{user_to_delete}** supprimé.")
        except Exception as e:
            st.session_state["delete_msg"] = ("error", f"Erreur SQL : {e}")

        st.rerun()

    # ⭐ MESSAGE AFFICHÉ ICI (juste après bouton Supprimer)
    if "delete_msg" in st.session_state:
        msg_type, msg = st.session_state["delete_msg"]
        if msg_type == "success":
            st.success(msg)
        else:
            st.error(msg)
        del st.session_state["delete_msg"]

    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ============================
    #  🔄 MODIFIER LE RÔLE
    # ============================
    st.markdown("### 🔄 Modifier le rôle")

    colA, colB = st.columns(2)
    with colA:
        user_role_select = st.selectbox("Utilisateur", user_list, key="modify_user")

    with colB:
        new_role_value = st.selectbox("Nouveau rôle", ["viewer", "admin"], key="modify_role")

    update_btn = st.button("Modifier le rôle")

    if update_btn:
        try:
            with engine.begin() as conn:
                conn.execute(text("UPDATE users SET role = :r WHERE username = :u"),
                             {"u": user_role_select, "r": new_role_value})
            st.session_state["modify_msg"] = ("success", f"Rôle de **{user_role_select}** mis à jour.")
        except Exception as e:
            st.session_state["modify_msg"] = ("error", f"Erreur SQL : {e}")

        st.rerun()

    # ⭐ MESSAGE AFFICHÉ ICI (juste après bouton Modifier)
    if "modify_msg" in st.session_state:
        msg_type, msg = st.session_state["modify_msg"]
        if msg_type == "success":
            st.success(msg)
        else:
            st.error(msg)
        del st.session_state["modify_msg"]

    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

# -----------------------------------------------------
# APPEL DE LA PAGE PARAMÉTRAGE
# -----------------------------------------------------
if st.session_state.page == "settings":
    page_settings()
    st.stop()

# -----------------------------------------------------
# PAGE 2 — ANALYSE (DESIGN D’ORIGINE INTACT)
# -----------------------------------------------------
if st.session_state.page == "main":

    # CSS original conservé
    st.markdown("""
       <style>
           .stApp { background-color:#001f3f !important; }
           h1,h3,label { color:white !important; }
           .metric-box {
               text-align:center;
               background-color:rgba(255,255,255,0.12);
               border-radius:12px;
               padding:15px;
               border:1px solid rgba(255,255,255,0.25);
               width:300px;
               margin:auto;
               color:white;
           }
           .response-box {
               background-color:white;
               color:black;
               border-left:6px solid #00e6ac;
               padding:25px;
               border-radius:12px;
               margin-top:25px;
           }
       </style>
    """, unsafe_allow_html=True)

    # Ligne : Retour à gauche / Colonne (Déconnexion + Langue) à droite
    left, empty, right = st.columns([1.2, 4.8, 1])

    with left:
        if st.button("← Retour au menu"):
            st.session_state.page = "selection"
            st.rerun()

    # Colonne droite contenant les deux widgets l'un sous l'autre
    with right:

        # Bouton déconnexion
        if st.button("⏻ Se déconnecter"):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.session_state.role = None
            st.session_state.page = "selection"
            st.rerun()

        # Selecteur de langue juste en dessous (même largeur)
        st.session_state.lang = st.selectbox(
            "Langue de réponse",
            ["Français", "English"],
            index=0 if st.session_state.lang == "Français" else 1
        )


    lang = st.session_state.lang
    theme = st.session_state.selected_domain

    # Titre
    st.markdown(f"<h1>🧠 Assistant Articles – {theme}</h1>", unsafe_allow_html=True)

    # Comptage articles
    with engine.begin() as conn:
        total_ai = conn.execute(text("SELECT COUNT(*) FROM ai_articles")).scalar()
        total_health = conn.execute(text("SELECT COUNT(*) FROM health_articles")).scalar()

    if theme == "Intelligence Artificielle":
        st.markdown(f"<div class='metric-box'><h2>🤖 {total_ai} articles</h2></div>", unsafe_allow_html=True)
        table_name = "ai_articles"
        emoji = "🤖"
        domain_prompt = "Tu es un expert en veille technologique spécialisée en IA."
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
    else:
        st.markdown(f"<div class='metric-box'><h2>🩺 {total_health} articles</h2></div>", unsafe_allow_html=True)
        table_name = "health_articles"
        emoji = "🩺"
        domain_prompt = "Tu es un expert en santé publique."
        api_key = os.getenv("MISTRAL_API_KEY_SANTE")
        base_url = os.getenv("MISTRAL_BASE_URL_SANTE")

    client = OpenAI(api_key=api_key, base_url=base_url)

    # Question utilisateur
    question = st.text_input(
        f"Posez votre question :",
        placeholder="Ex : Quelles sont les avancées récentes ?"
    )
    launch = st.button("✨ Analyser les articles")

    # Analyse
    if launch and question.strip():
        with engine.begin() as conn:
            df = pd.read_sql(text(f"""
                SELECT title, description, url, authors, published_at, source
                FROM {table_name}
                ORDER BY published_at DESC
                LIMIT 300
            """), conn)

        corpus = "\n\n".join([
            f"Titre: {row.title}\nDescription: {row.description}"
            for _, row in df.iterrows()
        ])

        lang_instruction = "Réponds en français." if lang == "Français" else "Answer in English."

        prompt = f"""
        Voici un ensemble d'articles :
        {corpus[:12000]}
        Question : {question}
        Réponds clairement. {lang_instruction}
        """

        response = client.chat.completions.create(
            model="mistral-small",
            messages=[
                {"role": "system", "content": domain_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400
        )

        answer = response.choices[0].message.content.strip()

        # ---- ENREGISTREMENT DU LOG ----
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO logs (username, question, domain, created_at)
                VALUES (:u, :q, :d, NOW())
            """), {
                "u": st.session_state.username,
                "q": question,
                "d": theme
            })

        # Affichage réponse
        st.markdown(
            f"""
            <div class='response-box'>
                <h3><b>{emoji} Réponse trouvée</b></h3>
                <p>{answer}</p>
            </div>
            """,
            unsafe_allow_html=True
        )
        with st.expander("📜 Articles utilisés pour cette analyse"):
            st.dataframe(df)


# -----------------------------------------------------
# PAGE 3 — STATISTIQUES (NOUVELLE VERSION AMÉLIORÉE)
# -----------------------------------------------------
def page_stats():

    # ======================== Vérification admin ============================
    if st.session_state.role != "admin":
        st.error("⛔ Accès refusé (Admin uniquement).")
        return

    # ======================== STYLE GLOBAL ============================
    st.markdown("""
        <style>

        /* === ARRIÈRE-PLAN GLOBAL === */
        .stApp {
            background-color:#001f3f !important;
        }

        /* === TITRES EN BLANC === */
        h1, h2, h3, .section-subtitle {
            color:white !important;
        }

        /* === BOUTON RETOUR (clair) === */
        div[data-testid="stButton"] button {
            background-color: #ffffff !important;
            color: #001f3f !important;
            border-radius: 6px !important;
            border: 1px solid #cccccc !important;
            font-weight: 600 !important;
        }
        div[data-testid="stButton"] button:hover {
            background-color: #e6e6e6 !important;
        }
        div[data-testid="stButton"] {
            margin-top: 20px !important;
            margin-bottom: 10px !important;
        }

        /* === SOUS-TITRE === */
        .section-subtitle {
            font-size: 22px !important;
            font-weight: 500 !important;
        }

        /* === BARRE DÉCORATIVE === */
        .blue-bar {
            height: 6px;
            width: 100%;
            background: linear-gradient(90deg, #0f172a, #1e3a8a, #0ea5e9);
            border-radius: 8px;
            margin: 25px 0;
        }

        /* === SELECTBOX (fond clair, TEXTE NOIR INTÉRIEUR) === */
        div[data-baseweb="select"] {
            background-color: #ffffff !important;
        }
        div[data-baseweb="select"] * {
            color:black !important;
        }
        ul[role="listbox"] {
            background-color:white !important;
        }
        ul[role="listbox"] li {
            color:black !important;
        }

        /* === DATE PICKER (champ + calendrier clair) === */
        input[type="text"], input[type="date"] {
            background-color:white !important;
            color:black !important;
        }
        div[role="dialog"] {
            background:white !important;
            color:black !important;
        }
        div[role="dialog"] * {
            color:black !important;
        }

        /* === MENUS 3 POINTS (KPIs) === */
        div[role="menu"] {
            background:white !important;
            color:black !important;
        }
        div[role="menu"] * {
            color:black !important;
        }

        /* === SCROLL BOX === */
        .scroll-box {
            max-height: 220px;
            overflow-y: auto;
            overflow-x: auto;
        }
        .scroll-box::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        .scroll-box::-webkit-scrollbar-thumb {
            background: #1E88E5;
            border-radius: 10px;
        }

        /* === LABELS (KPI + FILTRES) EN BLANC === */
        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] span,
        div[data-testid="stMetric"] * {
            color: white !important;
        }

        div[data-testid="stSelectbox"] label {
            color: white !important;
            font-weight: 700 !important;
        }

        div[data-testid="stDateInput"] label {
            color: white !important;
            font-weight: 700 !important;
        }

        </style>
    """, unsafe_allow_html=True)

    # ======================== Bouton retour ============================
    if st.button("⬅ Retour au menu"):
        st.session_state.page = "selection"
        st.rerun()

    # ============================= TITRE ====================================
    st.markdown(
        "<h1 style='text-align:center; color:white;'>📊 Tableau de bord - Statistiques</h1>",
        unsafe_allow_html=True
    )
    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ============================= CHARGEMENT LOGS ===========================
    with engine.begin() as conn:
        logs = pd.read_sql(
            text("""
                SELECT *
                FROM logs
                WHERE username != 'loubna'
                ORDER BY created_at DESC
            """),
            conn
        )

    if logs.empty:
        st.warning("Aucune donnée trouvée.")
        return

    logs["date"] = pd.to_datetime(logs["created_at"])

    # Conversion anglais → français
    day_mapping = {
        "Mon": "Lun",
        "Tue": "Mar",
        "Wed": "Mer",
        "Thu": "Jeu",
        "Fri": "Ven",
        "Sat": "Sam",
        "Sun": "Dim",
    }
    logs["weekday"] = logs["date"].dt.strftime("%a").map(day_mapping)

    # ========================================================================
    # 🎛️ FILTRES INTERACTIFS + KPI VIEWERS + KPI VIEWERS ACTIFS
    # ========================================================================
    f1, f1b, f2, f3 = st.columns([1.5, 1.5, 1.2, 1.2])

    # -------- KPI 1 : Nombre total de viewers --------
    with f1:
        st.markdown(
            "<div style='font-size:22px; font-weight:600; margin-bottom:-10px; color:white;'>👥 Nombre total de viewers</div>",
            unsafe_allow_html=True
        )
        with engine.begin() as conn:
            total_viewers = conn.execute(
                text("SELECT COUNT(*) FROM users WHERE role = 'viewer'")
            ).scalar()
        st.metric(label="", value=total_viewers)

    # -------- KPI 2 : Viewers actifs dans la période --------
    with f1b:
        st.markdown(
            "<div style='font-size:22px; font-weight:600; margin-bottom:-10px; color:white;'>🔥 Viewers actifs</div>",
            unsafe_allow_html=True
        )

        # Placeholder → sera rempli après filtrage
        kpi_active_viewers = st.empty()

    with f2:
        with engine.begin() as conn:
            existing_users = pd.read_sql( "SELECT username FROM users ORDER BY username", conn
            )["username"].tolist()

        # 🧹 Filtrer les logs pour ne garder que ceux d'utilisateurs encore existants
        logs = logs[logs["username"].isin(existing_users)]

        # 🧭 Liste pour le filtre utilisateur
        user_list = ["Tous les utilisateurs"] + existing_users
        selected_user = st.selectbox("👤 Utilisateur", user_list)        

    with f3:
        min_date = logs["date"].min().date()
        max_date = logs["date"].max().date()
        selected_dates = st.date_input("📅 Période", value=(min_date, max_date))

    # ======================= APPLICATION DES FILTRES ========================
    filtered_logs = logs.copy()

    if selected_user != "Tous les utilisateurs":
        filtered_logs = filtered_logs[filtered_logs["username"] == selected_user]

    start_date, end_date = selected_dates
    filtered_logs = filtered_logs[
        (filtered_logs["date"].dt.date >= start_date) &
        (filtered_logs["date"].dt.date <= end_date)
    ]
    # =================================================
    # 🔥 KPI dynamique : Viewers actifs
    # =================================================
    active_viewers = filtered_logs["username"].nunique()
    kpi_active_viewers.metric(label="", value=active_viewers)
    
    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ============================= STATISTIQUES ==============================
    vc_questions = filtered_logs["question"].value_counts()
    vc_questions = vc_questions[vc_questions >= 2]

    vc_domains = filtered_logs["domain"].value_counts()

    vc_users_per_day = filtered_logs.groupby(
        ["weekday", "username"]
    ).size().reset_index(name="count")

    order_days = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    vc_users_per_day["weekday"] = pd.Categorical(vc_users_per_day["weekday"], order_days)

    vc_days = filtered_logs.groupby("weekday").size().reindex(order_days).fillna(0)

    # ========================================================================
    # 🟥 TOP 10 QUESTIONS + PIE
    # ========================================================================
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("### 🔝 Top 10 questions les plus posées")
        df_top = vc_questions.head(10).reset_index()
        df_top.columns = ["Question", "Fréquence"]

        st.markdown("<div class='scroll-box'>", unsafe_allow_html=True)
        st.dataframe(df_top, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("### 🏆 Répartition par domaine")
        fig, ax = plt.subplots(figsize=(3.5, 3.5))
        ax.pie(vc_domains.values, labels=vc_domains.index, autopct="%1.1f%%")
        ax.set_aspect("equal")
        st.pyplot(fig)

    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ========================================================================
    # 🟩 COURBES UTILISATEURS & JOUR
    # ========================================================================
    colA, colB = st.columns(2)

    with colA:
        st.markdown("### 👤 Requêtes par utilisateur")
        pivot = vc_users_per_day.pivot(index="weekday",
                                       columns="username",
                                       values="count").fillna(0)
        st.line_chart(pivot, height=300)

    with colB:
        st.markdown("### 📅 Nombre total de requêtes par jour")
        st.line_chart(vc_days, height=300)

    st.markdown("<div class='blue-bar'></div>", unsafe_allow_html=True)

    # ========================================================================
    # 🟨 HISTORIQUE FILTRÉ
    # ========================================================================
    st.markdown("### Historiques")
    st.markdown("<div class='scroll-box'>", unsafe_allow_html=True)
    st.dataframe(filtered_logs, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------
# APPEL DE LA PAGE STATS  (toujours APRÈS la définition)
# -----------------------------------------------------

if st.session_state.page == "stats":
    page_stats()
    st.stop()
