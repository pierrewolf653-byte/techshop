from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from database import engine, SessionLocal
import json
import pandas as pd
import io
import os
import httpx
import bcrypt
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from apscheduler.schedulers.background import BackgroundScheduler
from groq import Groq  # <--- IMPORT GROQ

load_dotenv()

# --- LOGS DE DÉMARRAGE ---
print("🔍 Démarrage de main.py")
print(f"GROQ_API_KEY définie ? {bool(os.getenv('GROQ_API_KEY'))}")

from models import Base, Product as ProductModel, Contact, User, Order
from products import router as products_router

Base.metadata.create_all(bind=engine)

SECRET_KEY = os.getenv("SECRET_KEY", "votre_cle_secrete_changez_la")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="client/login")

def get_password_hash(password: str) -> str:
    password_bytes = password[:72].encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_bytes = plain_password[:72].encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(plain_bytes, hashed_bytes)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

app = FastAPI()
app.include_router(products_router)
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    db = SessionLocal()
    if db.query(ProductModel).count() == 0:
        with open("products.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                product = ProductModel(**item)
                db.add(product)
        db.commit()
    db.close()

def init_admin():
    db = SessionLocal()
    admin = db.query(User).filter(User.email == "admin@techshop.com").first()
    if not admin:
        hashed = get_password_hash("admin123")
        admin_user = User(
            nom="Administrateur",
            email="admin@techshop.com",
            hashed_password=hashed,
            role="admin"
        )
        db.add(admin_user)
        db.commit()
        print("✅ Admin créé : admin@techshop.com / admin123")
    db.close()

@app.post("/upload-contacts")
async def upload_contacts(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.csv')):
        raise HTTPException(400, "Format non supporté. Utilisez .xlsx ou .csv")
    contents = await file.read()
    if file.filename.endswith('.csv'):
        df = pd.read_csv(io.BytesIO(contents))
    else:
        df = pd.read_excel(io.BytesIO(contents))
    required = ['nom', 'telephone', 'email']
    for col in required:
        if col not in df.columns:
            raise HTTPException(400, f"Colonne '{col}' manquante")
    for _, row in df.iterrows():
        contact = Contact(
            nom=row['nom'],
            telephone=str(row['telephone']) if pd.notna(row['telephone']) else None,
            email=row['email'] if pd.notna(row['email']) else None,
            interets=row.get('interets', None),
            group_id=None
        )
        db.add(contact)
    db.commit()
    return {"message": f"{len(df)} contacts importés avec succès"}

@app.post("/analyze-interests")
def analyze_interests(db: Session = Depends(get_db)):
    contacts = db.query(Contact).all()
    keywords = {
        "gaming": ["gaming", "jeu", "rtx", "gamer", "souris gaming"],
        "bureautique": ["bureautique", "excel", "word", "office", "travail"],
        "stockage": ["stockage", "disque dur", "ssd", "nas", "sauvegarde"]
    }
    group_map = {"gaming": 1, "bureautique": 2, "stockage": 3}
    updated = 0
    for contact in contacts:
        if contact.interets:
            texte = contact.interets.lower()
            for cat, mots in keywords.items():
                if any(mot in texte for mot in mots):
                    contact.group_id = group_map[cat]
                    updated += 1
                    break
    db.commit()
    return {"message": f"Analyse terminée, {updated} contacts ont reçu un groupe"}

@app.get("/generate-ads/{group_id}")
def generate_ads(group_id: int, db: Session = Depends(get_db)):
    contacts = db.query(Contact).filter(Contact.group_id == group_id).all()
    if not contacts:
        return {"error": "Aucun contact dans ce groupe"}
    group_cat = {1: "gaming", 2: "bureautique", 3: "stockage"}
    cat = group_cat.get(group_id, "informatique")
    products = db.query(ProductModel).filter(ProductModel.category == cat).limit(3).all()
    product_names = [p.name for p in products]
    pub = f"Offre spéciale pour vous ! Découvrez nos produits {cat} : {', '.join(product_names)}. Visitez notre site dès maintenant !"
    return {
        "group_id": group_id,
        "nb_contacts": len(contacts),
        "publicite": pub,
        "produits_associes": product_names,
        "statut_envoi": f"Simulé - destinataires: {', '.join([c.nom for c in contacts[:3]])}" + ("..." if len(contacts)>3 else "")
    }

@app.post("/client/register")
def register(nom: str, email: str, password: str, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(400, "Cet email est déjà utilisé")
    hashed = get_password_hash(password)
    new_user = User(nom=nom, email=email, hashed_password=hashed, role="user")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Utilisateur créé avec succès", "id": new_user.id}

@app.post("/client/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(401, "Email ou mot de passe incorrect")
    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id, "nom": user.nom, "role": user.role}

@app.get("/client/profile")
def get_profile(token: str = Header(...), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(401, "Token invalide")
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise HTTPException(401, "Utilisateur non trouvé")
        return {"id": user.id, "nom": user.nom, "email": user.email, "role": user.role}
    except JWTError:
        raise HTTPException(401, "Token invalide ou expiré")

# ---------- CHAT IA AVEC GROQ ----------
@app.post("/chat")
async def chat(message: str, history: str = "", token: str = Header(...)):
    # --- LOGS DE DÉBOGAGE ---
    print(f"📩 Message reçu : {message[:30]}..." if message else "📩 Message reçu (vide)")
    groq_api_key = os.getenv("GROQ_API_KEY")
    print(f"🔑 Clé GROQ : {'✅ présente' if groq_api_key else '❌ manquante'}")

    # 1. Vérification du token JWT
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(401, "Token invalide")
    except JWTError:
        raise HTTPException(401, "Token invalide ou expiré")

    # 2. Construction des messages
    messages = [
        {
            "role": "system",
            "content": "Tu es un assistant commercial pour TechShop, un site de vente de matériel informatique. Réponds de manière professionnelle et chaleureuse."
        }
    ]

    if history:
        try:
            history_list = json.loads(history)
            if len(history_list) > 20:
                history_list = history_list[-20:]
            messages.extend(history_list)
        except:
            pass

    messages.append({"role": "user", "content": message})

    # 3. Appel à l'API Groq
    try:
        if not groq_api_key:
            print("❌ GROQ_API_KEY non définie dans les variables d'environnement")
            raise HTTPException(500, "GROQ_API_KEY non définie")

        client = Groq(api_key=groq_api_key)

        chat_completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",  # Modèle gratuit et rapide
            messages=messages,
            temperature=0.7,
            max_tokens=300,
            top_p=1,
            stream=False
        )

        reply = chat_completion.choices[0].message.content
        print(f"✅ Réponse générée : {reply[:50]}...")
        return {"reponse": reply}

    except Exception as e:
        print(f"❌ Erreur Groq : {str(e)}")
        raise HTTPException(500, f"Erreur de l'IA : {str(e)}")

# ---------- PANIER ET PAIEMENT ----------
@app.post("/cart/add")
def add_to_cart(
    product_id: int = Form(...),
    quantity: int = Form(1),
    db: Session = Depends(get_db)
):
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not product:
        raise HTTPException(404, "Produit non trouvé")
    return {"message": f"Produit {product.name} ajouté au panier", "product": product.name, "price": product.price}

@app.post("/checkout")
def checkout(payment_method: str = Form(...), token: str = Header(...), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_email = payload.get("sub")
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            raise HTTPException(401, "Utilisateur non trouvé")
    except JWTError:
        raise HTTPException(401, "Token invalide")

    if payment_method not in ["moncash", "natcash"]:
        raise HTTPException(400, "Méthode de paiement invalide")
    order = Order(
        user_id=user.id,
        products=json.dumps([{"id": 1, "name": "PC Gamer Extreme", "price": 1499.99, "qty": 1}]),
        total=1499.99,
        payment_method=payment_method,
        status="paid",
        created_at=datetime.now().isoformat()
    )
    db.add(order)
    db.commit()
    return {"message": f"Paiement simulé avec {payment_method} réussi !", "order_id": order.id}

@app.get("/admin/orders")
def admin_orders(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    result = []
    for o in orders:
        result.append({
            "id": o.id,
            "user_id": o.user_id,
            "products": json.loads(o.products),
            "total": o.total,
            "status": o.status,
            "payment_method": o.payment_method,
            "created_at": o.created_at
        })
    return result

# ---------- WHATSAPP ----------
def send_whatsapp_pywhatkit(to_number: str, message: str, wait_time: int = 30) -> bool:
    try:
        import pywhatkit as kit
        kit.sendwhatmsg_instantly(
            phone_no=to_number,
            message=message,
            wait_time=wait_time,
            tab_close=True,
            close_time=5
        )
        print(f"✅ Message envoyé à {to_number}")
        return True
    except ImportError:
        print(f"🔁 [SIMULATION] pywhatkit non disponible, message envoyé à {to_number}")
        return True
    except Exception as e:
        print(f"❌ Erreur pywhatkit : {e}")
        return False

@app.post("/send-campaign/{group_id}")
def send_campaign(group_id: int, db: Session = Depends(get_db)):
    contacts = db.query(Contact).filter(Contact.group_id == group_id).all()
    if not contacts:
        raise HTTPException(404, "Aucun contact dans ce groupe")
    ad_data = generate_ads(group_id, db)
    if "error" in ad_data:
        raise HTTPException(500, ad_data["error"])
    message = ad_data["publicite"]
    sent = 0
    failed = []
    for contact in contacts:
        if not contact.telephone:
            failed.append({"nom": contact.nom, "reason": "Pas de téléphone"})
            continue
        phone = contact.telephone.replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+" + phone
        success = send_whatsapp_pywhatkit(phone, message)
        if success:
            sent += 1
        else:
            failed.append({"nom": contact.nom, "reason": "Erreur pywhatkit"})
    return {"group_id": group_id, "message": message, "sent": sent, "failed": len(failed), "failed_list": failed}

# ---------- FACEBOOK ----------
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")

def post_to_facebook_page(message: str) -> bool:
    if not FACEBOOK_PAGE_ACCESS_TOKEN or not FACEBOOK_PAGE_ID:
        print("⚠️ Identifiants Facebook manquants")
        return False
    url = f"https://graph.facebook.com/v22.0/{FACEBOOK_PAGE_ID}/feed"
    params = {"message": message[:5000], "access_token": FACEBOOK_PAGE_ACCESS_TOKEN}
    try:
        response = requests.post(url, params=params)
        response.raise_for_status()
        print("✅ Publication Facebook réussie")
        return True
    except Exception as e:
        print(f"❌ Erreur Facebook : {e}")
        return False

@app.post("/send-campaign-facebook/{group_id}")
def send_campaign_facebook(group_id: int, db: Session = Depends(get_db)):
    ad_data = generate_ads(group_id, db)
    if "error" in ad_data:
        raise HTTPException(500, ad_data["error"])
    message = ad_data["publicite"]
    success = post_to_facebook_page(message)
    return {"group_id": group_id, "message": message, "published": success, "page_id": FACEBOOK_PAGE_ID}

# ---------- CAMPAGNE AUTOMATIQUE ----------
@app.post("/auto-campaign")
def auto_campaign(db: Session = Depends(get_db)):
    analyze_interests(db)
    groups = db.query(Contact.group_id).distinct().filter(Contact.group_id.isnot(None)).all()
    if not groups:
        return {"error": "Aucun groupe trouvé. Importez d'abord des contacts et lancez l'analyse."}
    results = []
    for group in groups:
        gid = group[0]
        ad_data = generate_ads(gid, db)
        if "error" in ad_data:
            results.append({"group_id": gid, "error": ad_data["error"]})
            continue
        contacts = db.query(Contact).filter(Contact.group_id == gid).all()
        sent = 0
        failed = []
        for contact in contacts:
            if not contact.telephone:
                failed.append({"nom": contact.nom, "reason": "Pas de téléphone"})
                continue
            phone = contact.telephone.replace(" ", "").replace("-", "")
            if not phone.startswith("+"):
                phone = "+" + phone
            if send_whatsapp_pywhatkit(phone, ad_data["publicite"]):
                sent += 1
            else:
                failed.append({"nom": contact.nom, "reason": "Erreur pywhatkit"})
        results.append({
            "group_id": gid,
            "publicite": ad_data["publicite"],
            "contacts_envoyes": sent,
            "total_contacts": len(contacts),
            "failed": failed
        })
    return {"message": "Campagne automatique terminée", "resultats": results}

# ---------- PLANIFICATION AUTOMATIQUE ----------
def scheduled_campaign():
    print("🔁 Lancement de la campagne automatique programmée...")
    db = SessionLocal()
    try:
        groups = db.query(Contact.group_id).distinct().filter(Contact.group_id.isnot(None)).all()
        if not groups:
            print("Aucun groupe trouvé.")
            return
        for group in groups:
            gid = group[0]
            ad_data = generate_ads(gid, db)
            if "error" in ad_data:
                continue
            contacts = db.query(Contact).filter(Contact.group_id == gid).all()
            for contact in contacts:
                if contact.telephone:
                    phone = contact.telephone.replace(" ", "").replace("-", "")
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    send_whatsapp_pywhatkit(phone, ad_data["publicite"])
        print("✅ Campagne automatique terminée")
    except Exception as e:
        print(f"❌ Erreur : {e}")
    finally:
        db.close()

# ---------- ORDRES CLIENT ----------
@app.get("/client/orders")
def get_user_orders(token: str = Header(...), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(401, "Utilisateur non trouvé")
        orders = db.query(Order).filter(Order.user_id == user.id).all()
        result = []
        for o in orders:
            products = []
            try:
                if isinstance(o.products, str):
                    products = json.loads(o.products)
                else:
                    products = o.products
            except:
                products = [{"name": "Produit inconnu", "price": 0}]
            if not isinstance(products, list):
                products = [{"name": str(products), "price": 0}]
            result.append({
                "id": o.id,
                "products": products,
                "total": float(o.total) if o.total else 0,
                "status": o.status or "pending",
                "payment_method": o.payment_method or "inconnu",
                "created_at": o.created_at or datetime.now().isoformat()
            })
        return result
    except JWTError:
        raise HTTPException(401, "Token invalide")
    except Exception as e:
        raise HTTPException(500, f"Erreur interne : {str(e)}")

# ---------- ADMIN : GESTION DES PRODUITS ----------
@app.post("/admin/product/add")
def admin_add_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image_url: str = Form(...),
    db: Session = Depends(get_db)
):
    product = ProductModel(
        name=name,
        description=description,
        price=price,
        category=category,
        image_url=image_url
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"message": "Produit ajouté avec succès", "product_id": product.id}

@app.delete("/admin/product/{product_id}")
def admin_delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not product:
        raise HTTPException(404, "Produit non trouvé")
    db.delete(product)
    db.commit()
    return {"message": f"Produit {product.name} supprimé"}

@app.put("/admin/product/{product_id}")
def admin_update_product(
    product_id: int,
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image_url: str = Form(...),
    db: Session = Depends(get_db)
):
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if not product:
        raise HTTPException(404, "Produit non trouvé")
    product.name = name
    product.description = description
    product.price = price
    product.category = category
    product.image_url = image_url
    db.commit()
    return {"message": f"Produit {product.name} mis à jour"}

# ---------- ADMIN : GESTION DES UTILISATEURS ----------
@app.get("/admin/users")
def admin_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "nom": u.nom, "email": u.email, "role": u.role, "is_active": u.is_active} for u in users]

@app.put("/admin/user/{user_id}/role")
def admin_update_user_role(user_id: int, role: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé")
    user.role = role
    db.commit()
    return {"message": f"Rôle de {user.nom} mis à jour en {role}"}

@app.delete("/admin/user/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé")
    db.delete(user)
    db.commit()
    return {"message": f"Utilisateur {user.nom} supprimé"}

# ---------- ADMIN : STATISTIQUES COMPLÈTES ----------
@app.get("/admin/dashboard-stats")
def admin_dashboard_stats(db: Session = Depends(get_db)):
    contacts_total = db.query(Contact).count()
    contacts_avec_groupe = db.query(Contact).filter(Contact.group_id.isnot(None)).count()
    produits_total = db.query(ProductModel).count()
    users_total = db.query(User).count()
    orders_total = db.query(Order).count()
    orders_paid = db.query(Order).filter(Order.status == "paid").count()
    orders_pending = db.query(Order).filter(Order.status == "pending").count()
    return {
        "contacts_total": contacts_total,
        "contacts_avec_groupe": contacts_avec_groupe,
        "produits_total": produits_total,
        "users_total": users_total,
        "orders_total": orders_total,
        "orders_paid": orders_paid,
        "orders_pending": orders_pending
    }

# ---------- ADMIN : CONTACTS, GROUPES ----------
@app.get("/admin/stats")
def admin_stats(db: Session = Depends(get_db)):
    contacts_total = db.query(Contact).count()
    contacts_avec_groupe = db.query(Contact).filter(Contact.group_id.isnot(None)).count()
    groupes_distincts = db.query(Contact.group_id).distinct().count()
    produits_total = db.query(ProductModel).count()
    return {
        "contacts_total": contacts_total,
        "contacts_avec_groupe": contacts_avec_groupe,
        "groupes_distincts": groupes_distincts,
        "produits_total": produits_total
    }

@app.get("/admin/contacts")
def admin_contacts(db: Session = Depends(get_db)):
    contacts = db.query(Contact).all()
    return [{"id": c.id, "nom": c.nom, "telephone": c.telephone, "email": c.email, "interets": c.interets, "group_id": c.group_id} for c in contacts]

@app.get("/admin/groups")
def admin_groups(db: Session = Depends(get_db)):
    groups = {}
    contacts = db.query(Contact).filter(Contact.group_id.isnot(None)).all()
    for c in contacts:
        gid = c.group_id
        groups.setdefault(gid, []).append(c.nom)
    group_cat = {1: "gaming", 2: "bureautique", 3: "stockage"}
    return [{"group_id": gid, "categorie": group_cat.get(gid, "inconnu"), "effectif": len(names), "membres": names} for gid, names in groups.items()]

@app.delete("/admin/contact/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(404, "Contact non trouvé")
    db.delete(contact)
    db.commit()
    return {"message": f"Contact {contact_id} supprimé"}

# ---------- PAGES PROTÉGÉES ----------
@app.get("/dashboard", response_class=HTMLResponse)
def user_dashboard(token: str = Header(None), token_q: str = None):
    tk = token or token_q
    if not tk:
        return HTMLResponse("""
            <html><head><title>Accès non autorisé</title></head>
            <body style="font-family: Arial; text-align: center; margin-top: 80px; background: #f8f9fa;">
                <h1 style="color: #dc3545;">🔐 Accès non autorisé</h1>
                <p style="font-size: 1.2rem;">Vous devez être connecté pour accéder à votre espace personnel.</p>
                <a href="/static/login_client.html" style="display: inline-block; margin-top: 20px; padding: 12px 30px; background: #6c5ce7; color: white; text-decoration: none; border-radius: 50px;">Se connecter</a>
            </body></html>
        """, status_code=401)
    try:
        jwt.decode(tk, SECRET_KEY, algorithms=[ALGORITHM])
        with open("static/user/index.html", "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(html)
    except JWTError:
        return HTMLResponse("""
            <html><head><title>Session expirée</title></head>
            <body style="font-family: Arial; text-align: center; margin-top: 80px; background: #f8f9fa;">
                <h1 style="color: #ffc107;">⏳ Session expirée</h1>
                <p style="font-size: 1.2rem;">Veuillez vous reconnecter.</p>
                <a href="/static/login_client.html" style="display: inline-block; margin-top: 20px; padding: 12px 30px; background: #6c5ce7; color: white; text-decoration: none; border-radius: 50px;">Se connecter</a>
            </body></html>
        """, status_code=401)

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(token: str = Header(None), token_q: str = None):
    tk = token or token_q
    if not tk:
        return HTMLResponse("""
            <html><head><title>Accès réservé</title></head>
            <body style="font-family: Arial; text-align: center; margin-top: 80px; background: #f8f9fa;">
                <h1 style="color: #dc3545;">🔐 Accès réservé</h1>
                <p style="font-size: 1.2rem;">Vous devez être administrateur pour accéder à cette page.</p>
                <a href="/static/login_client.html" style="display: inline-block; margin-top: 20px; padding: 12px 30px; background: #6c5ce7; color: white; text-decoration: none; border-radius: 50px;">Se connecter</a>
            </body></html>
        """, status_code=401)
    try:
        payload = jwt.decode(tk, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") != "admin":
            return HTMLResponse("""
                <html><head><title>Accès interdit</title></head>
                <body style="font-family: Arial; text-align: center; margin-top: 80px; background: #f8f9fa;">
                    <h1 style="color: #dc3545;">⛔ Accès interdit</h1>
                    <p style="font-size: 1.2rem;">Vous ne disposez pas des droits d'administration.</p>
                    <a href="/static/index.html" style="display: inline-block; margin-top: 20px; padding: 12px 30px; background: #6c757d; color: white; text-decoration: none; border-radius: 50px;">Retour à l'accueil</a>
                </body></html>
            """, status_code=403)
        with open("static/admin/index.html", "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(html)
    except JWTError:
        return HTMLResponse("""
            <html><head><title>Session expirée</title></head>
            <body style="font-family: Arial; text-align: center; margin-top: 80px; background: #f8f9fa;">
                <h1 style="color: #ffc107;">⏳ Session expirée</h1>
                <p style="font-size: 1.2rem;">Veuillez vous reconnecter.</p>
                <a href="/static/login_client.html" style="display: inline-block; margin-top: 20px; padding: 12px 30px; background: #6c5ce7; color: white; text-decoration: none; border-radius: 50px;">Se connecter</a>
            </body></html>
        """, status_code=401)

# ---------- LANCEMENT DU SERVEUR ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)